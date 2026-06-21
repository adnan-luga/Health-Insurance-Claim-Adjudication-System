from docling_core.types.doc import TextItem
from docling_core.types.doc import TableItem
import re
from docling_core.types.doc import SectionHeaderItem
from docling_core.types.doc import DoclingDocument
from tokenizers.implementations import byte_level_bpe
from dataclasses import dataclass
from pathlib import Path
import hashlib
from docling.document_converter import PdfFormatOption
from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
from docling.datamodel.base_models import InputFormat

source = "../../data/02_SecureHealth_Policy_Wording.pdf"

@dataclass
class ParsedSection:
    section_id: str
    section_title: str
    page_start: int
    page_end: int
    raw_markdown: str
    tables: list[dict]
    confidence: float

@dataclass
class ParsedDocument:
    document_hash: str # SHA256 of original bytes
    total_pages: int
    sections: list[ParsedSection]
    raw_full_markdown: str
    metadata: dict    # Author, creation date, etc.
    parser_warnings: list[str]


class DocumentParser:
    def __init__(self):

        pipeline_options = PdfPipelineOptions()

        # Table reconstruction
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options = TableStructureOptions(
            do_cell_matching=True,  # Match text to cells precisely
            mode="accurate",        # Use the most accurate mode (vs. fast - we want accuracy)
        )
        self.converter = DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        })

    def parse(self, source: str | Path | bytes) -> ParsedDocument:
        # Compute document hash before parsing
        if isinstance(source, bytes):
            doc_hash = hashlib.sha256(source).hexdigest()
            temp_path = Path(f"/tmp/{doc_hash}.pdf")
            temp_path.write_bytes(source)
            source= temp_path
        else:
            doc_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        
        result = self.converter.convert(str(source))
        doc: DoclingDocument = result.document

        warnings = []
        sections = []

        # Process each section in document order
        for section_group in self._group_by_section(doc):
            parsed_section = self._process_section(section_group, doc)

            if parsed_section.confidence < 0.7:
                warnings.append(
                    f"Low confidence ({parsed_section.confidence:.2f})"
                    f" for section {parsed_section.section_title}"
                )
            sections.append(parsed_section)

        return ParsedDocument(
            document_hash=doc_hash,
            total_pages=doc.num_pages(),
            sections=sections,
            raw_full_markdown=doc.export_to_markdown(doc),
            metadata=self._extract_metadata(doc),
            parser_warnings=warnings
        )
            


    def _process_section(self, items, doc: DoclingDocument) -> ParsedSection:
        """Convert a gorup of DoclingDocument items into a ParsedSection"""
        tables = []
        text_parts = []
        pages = []

        for item in items:
            item_prov = getattr(item, "prov", None)
            if item_prov:
                pages.extend([p.page_no for p in item_prov])


            if isinstance(item, TableItem):
                # Export table as both Markdown and JSON
                table_dict = {
                    "markdown":item.export_to_markdown(doc),
                    "dataframe":item.export_to_dataframe(doc).to_dict(orient="records"),
                    "cells":self._extract_table_cells(item, doc),
                    "confidence":getattr(item, "confidence", 1.0),
                }
                tables.append(table_dict)
                text_parts.append(item.export_to_markdown(doc))
            
            elif isinstance(item, TextItem):
                text_parts.append(item.text)

        section_markdown = "\n\n".join(text_parts)
        avg_confidence = sum(
            t["confidence"] for t in tables
        )/ len(tables) if tables else 1.0

        return ParsedSection(
            section_id=self._make_section_id(items[0]),
            section_title=self._extract_section_title(items),
            page_start=min(pages) if pages else 0,
            page_end=max(pages) if pages else 0,
            raw_markdown=section_markdown,
            tables=tables,
            confidence=avg_confidence
        )
        
    def _group_by_section(self, doc: DoclingDocument) -> list[list]:
        """Group document items by their heading sections"""

        grouped_sections = []
        current_section = []

        # Iterate through the doc's sequential body tree
        for node in doc.body.children:
            # Resolve the actual document element (Text, Table, Group, etc.)
            item = node.resolve(doc)

            if item is None:
                continue
            # Check if the element is an H1, H2, or any other SectionHeaderItem
            if isinstance(item, SectionHeaderItem):
                # Save the previous section if it contains elements
                if current_section:
                    grouped_sections.append(current_section)
                
                current_section = [item]
            else:
                # Append all body text, teables, or structures to the active section
                current_section.append(item)

        # Append the final section block after loop completion
        if current_section:
            grouped_sections.append(current_section)
        
        return grouped_sections
    
    def _make_section_id(self, first_item) -> str:
        """
        Generate a clea, and unique ID for a section block.
        """
        base_text = "section"
        unique_seed="0"

        if first_item is not None:
            if hasattr(first_item, "text") and first_item.text:
                base_text = first_item.text.strip().lower()

            if hasattr(first_item, "prov") and first_item.prov:
                unique_seed = str(first_item.prov[0].page_no) + str(first_item.prov[0].bbox)
            elif hasattr(first_item, "self_ref"):
                unique_seed = str(first_item.self_ref)
        
        slug = re.sub(r"[^a-z0-9\-_]+", "-", base_text)
        slug = re.sub(r"-+", "-", slug).strip("-")
        slug = slug[:30] if slug else "section"

        hash_suffix = hashlib.md5(unique_seed.encode("utf-8")).hexdigest()[:8]
        return f"{slug}-{hash_suffix}"
    
    def _extract_section_title(self, items: list) -> str:
        """Extract the string title from a grouped section list"""

        for item in items:
            if isinstance(item, SectionHeaderItem):
                return item.text.strip()

        return "Untitled Section"

    def _extract_metadata(self, doc: DoclingDocument) -> dict:
        """Extract metadata from document"""

        metadata = {
            "filename": "Unknown",
            "mime_type": "Unknown",
            "file_size_bytes": None,
            "hash": None,
            "total_pages": 0,
            "schema_version": getattr(doc, "version", "Unknown"),
        }

        if hasattr(doc, "origin") and doc.origin is not None:
            origin = doc.origin
            metadata["filename"] = getattr(origin, "filename", metadata["filename"])
            metadata["mime_type"] = getattr(origin, "mime_type", metadata["mime_type"])
            metadata["file_size_bytes"] = getattr(origin, "size_bytes", None)

            if hasattr(origin, "hash") and origin.hash:
                metadata["hash"] = origin.binary_hash
        
        if hasattr(doc, "pages") and doc.pages:
            if isinstance(doc.pages, dict):
                metadata["total_pages"] = len(doc.pages)
            elif hasattr(doc.pages, "__len__"):
                metadata["total_pages"] = len(doc.pages)

        if metadata["total_pages"] == 0 and hasattr(doc, "texts"):
            page_set = set()
            for item in doc.texts:
                if hasattr(item, "prov") and item.prov:
                    for p in item.prov:
                        if hasattr(p, "page_no"):
                            page_set.add(p.page_no)
            if page_set:
                metadata["total_pages"] = max(page_set)
        
        return metadata
    
    def _extract_table_cells(self, table: TableItem, doc: DoclingDocument) -> list[dict]:
        """Extract all table cells with their detailed properties"""
        cells = []
        df = table.export_to_dataframe(doc)

        parent_label = None

        for _,row in df.iterrows():
            row_values = row.tolist()
            non_empty = [v for v in row_values if str(v).strip() not in ("","N/A", "nan")]

            if len(non_empty) == 1:
                parent_label = non_empty[0]
                continue

            cell_dict = {
                col: str(val).strip()
                for col, val in zip(df.columns, row_values)
            }

            if parent_label:
                cell_dict["__parent_label__"] = parent_label

            cells.append(cell_dict)

        return cells
            

        
