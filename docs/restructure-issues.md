# Folder Restructure — Issues to Address

## Must Fix (during restructure)

1. **`load_dotenv()` CWD vs script dir**
   - `load_dotenv()` without args searches CWD, not script directory
   - All scripts must use: `load_dotenv(Path(__file__).parent / ".env")`
   - Affects: `local-agent/strands_agent.py`, `managed-agentcore/agentcore_runtime.py`, `01_create`, `02_invoke`

2. **`STRANDS_NON_INTERACTIVE` in container**
   - Shell tool needs this to skip confirmation prompts
   - Must pass via `env_vars` in `launch()`: `{"STRANDS_NON_INTERACTIVE": "true"}`

3. **`.gitignore` subdirectory patterns**
   - Current `.env` pattern only matches root level
   - Add: `*/.env` and `managed-agentcore/skills/`

4. **`01_create` working directory**
   - Must `os.chdir(Path(__file__).parent)` so Docker context = `managed-agentcore/`
   - Skills copy: `shutil.copytree("../skills", "./skills", dirs_exist_ok=True)`

## Document (in README)

5. **Container IAM role needs SSM permissions**
   - `auto_create_execution_role=True` creates role with Bedrock + ECR + CloudWatch only
   - `github_standup.py` calls `ssm:GetParameter` + `kms:Decrypt` — not in auto-created role
   - Must add SSM permissions to execution role after first deploy
