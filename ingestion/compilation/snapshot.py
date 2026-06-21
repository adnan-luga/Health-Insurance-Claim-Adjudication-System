import yaml
import aiofiles
from pathlib import Path
from ingestion.extraction.schemas import PolicyRuleSet

class PolicySnapshot:
    def __init__(self, output_dir: str = "snapshots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    async def save_yaml(self, ruleset: PolicyRuleSet) -> str:
    
        file_path = self.output_dir / f"{ruleset.policy_id}_{ruleset.version_hash}.yaml"
        
        # Pydantic dump dict -> yaml
        data = ruleset.model_dump(mode="json")
        yaml_content = yaml.dump(data, sort_keys=False, allow_unicode=True)
        
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(yaml_content)
            
        return str(file_path)