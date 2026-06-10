# Modelserver Runbook

Operational notes for the modelserver lean inference container.

## Image size check (< 500 MB)

After building, verify the image stays under 500 MB (D1/Principle VI):

```bash
docker compose build modelserver
docker images pantera-modelserver --format "{{.Size}}"
# Or inspect directly:
docker image inspect pantera_modelserver --format "{{.Size}}" | awk '{printf "%.0f MB\n", $1/1024/1024}'
```

If the image grows beyond 500 MB:
- Ensure `uv sync --only-group modelserver --no-install-project` is used in the Dockerfile (not `--group`, which pulls in `[project].dependencies`).
- The `training` group (torch ~2 GB) must never appear in the serving image.
- The `modelserver` group is self-contained: fastapi, uvicorn, onnxruntime, numpy, tokenizers, pydantic, pydantic-settings, structlog, hvac, secure, scikit-learn, joblib, pyyaml.

## Git LFS for large artifacts

If any artifact in `modelserver/models/` exceeds 100 MB, track it with Git LFS:

```bash
git lfs track "modelserver/models/*.onnx"
git lfs track "modelserver/models/*.joblib"
git add .gitattributes
git add modelserver/models/
git commit -m "chore(models): track large artifacts with Git LFS"
```

Check tracked files:
```bash
git lfs ls-files
```

Current artifacts (v1.0) are small (< 5 MB). Git LFS is only needed if a production
BiomedBERT ONNX model replaces the current Gather-based placeholder.

## Rotating the modelserver_token

The service reads its token from Vault at startup (`pantera/secrets.modelserver_token`).
Rotation requires no code change:

1. Write the new token to Vault:
```bash
uv run python - <<'PY'
import hvac, os
c = hvac.Client(url=os.environ["VAULT_ADDR"], token=os.environ["VAULT_TOKEN"])
c.secrets.kv.v2.create_or_update_secret(
    path="pantera/secrets",
    secret={"modelserver_token": "NEW_TOKEN_VALUE"},
)
PY
```

2. Restart the modelserver container to pick up the new token:
```bash
docker compose restart modelserver
```

3. Update callers (app service) to use the new token (write to Vault under the same key and restart the api/worker containers). The modelserver validates the token on every request via `hmac.compare_digest` — the new value takes effect immediately on next restart.

## Updating model artifacts

1. Regenerate artifacts:
```bash
uv run python scripts/generate_model_artifacts.py  # minimal dev artifacts
# OR run notebooks/01_train_export_modelserver.ipynb for production BiomedBERT
```

2. Verify manifest SHA-256s are correct:
```bash
uv run python modelserver/eval/run_eval.py  # must print PASS
```

3. Rebuild and test:
```bash
docker compose build modelserver
docker compose up -d --wait modelserver
curl http://localhost:8001/ready  # should show new sha256 values
```
