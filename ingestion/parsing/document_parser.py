from docling.document_converter import PdfFormatOption
from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
from docling.datamodel.base_models import InputFormat


source = "../../data/02_SecureHealth_Policy_Wording.pdf"

pipeline_options = PdfPipelineOptions()
pipeline_options.do_table_structure = True
pipeline_options.table_structure_options = TableStructureOptions(
    do_cell_matching=True,
    mode="accurate"
)
converter = DocumentConverter(format_options={
    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
})
doc = converter.convert(source).document

print(doc.export_to_markdown())
