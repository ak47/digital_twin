# Terraform — digital_twin

From this directory:

```bash
export TF_VAR_project_id="YOUR_PROJECT_ID"
terraform init
terraform plan
terraform apply
```

After building and pushing your API image to Artifact Registry:

```bash
terraform apply -var="container_image=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/digital-twin-api/api:TAG"
```

See repository root `README.md` for full context.
