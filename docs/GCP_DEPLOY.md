# Deploying to Google Cloud: step by step

This guide takes the repo from your laptop to a live app on Google Cloud. When you finish you will have:

- **BigQuery** holding the inspections, refreshed every morning by a **Cloud Run job** that **Cloud Scheduler** starts
- **Cloud Run** serving the dashboard, the API, and the inspection agent from one container
- **Vertex AI** running the agent's model (Gemini) and the embeddings for food code search
- **Terraform** managing all of it, with **GitHub Actions** deploying on every push to `main` and running the agent evals on pull requests

Plan on about 2–3 hours the first time. Most of that is waiting for the first data load and the first build.

---

## 0. Before you start

Install these on your laptop:

| Tool | Check | Install |
| --- | --- | --- |
| Google Cloud CLI | `gcloud --version` | <https://cloud.google.com/sdk/docs/install> |
| Terraform 1.6+ | `terraform -version` | <https://developer.hashicorp.com/terraform/install> |
| Python 3.12 | `python3.12 --version` | python.org or Homebrew |
| Node 22 | `node --version` | nodejs.org or Homebrew (only for local frontend work) |

You also need a Google account with billing enabled. New accounts get free trial credit.

**Cost:** with scale-to-zero Cloud Run, the BigQuery free tier and a small dataset, this project should cost little beyond a few cents of Vertex AI usage per batch of questions. Set a budget anyway (step 1).

---

## 1. Create the project and a budget alert

```bash
export PROJECT=chicago-food-<something-unique>    # project IDs are global
gcloud projects create $PROJECT
gcloud config set project $PROJECT
```

1. Link billing: Console → **Billing** → **Link a billing account** → choose your project.
2. Add a budget: Console → **Billing** → **Budgets & alerts** → **Create budget**. Scope it to this project, set $10, and keep the 50%, 90% and 100% email alerts.

---

## 2. Sign in from your terminal

```bash
gcloud auth login                         # for gcloud commands
gcloud auth application-default login     # for Terraform and the Python scripts
gcloud auth application-default set-quota-project $PROJECT
```

---

## 3. Create the infrastructure with Terraform

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set project_id = "<your project ID>"
terraform init
terraform apply
```

Type `yes` when asked. This enables the APIs, then creates the BigQuery dataset and tables, the Artifact Registry repo, four service accounts, the Cloud Run service and job, the daily scheduler, and the GitHub sign-in (Workload Identity Federation).

- **If it fails with "API has not been used" or "SERVICE_DISABLED":** APIs take a minute to switch on. Run `terraform apply` again.
- The Cloud Run service starts out running Google's "hello" placeholder image. Step 4 replaces it.

Save the outputs. You need them in steps 4 and 9:

```bash
terraform output
cd ../..
```

---

## 4. Build and deploy the first image (Cloud Build)

Cloud Build builds the container in Google Cloud, so you don't need Docker on your laptop. In new projects, Cloud Build runs as the Compute Engine default service account. Give it permission to push images and deploy:

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
BUILD_SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
for ROLE in roles/run.developer roles/iam.serviceAccountUser \
            roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$BUILD_SA" --role=$ROLE --quiet >/dev/null
done
```

Then build and deploy from the repo root:

```bash
gcloud builds submit --config cloudbuild.yaml --substitutions=_TAG=v1
```

That builds the image (React and Python in one container), pushes it, deploys the web service, and points the ETL job at the same image. It takes about 5 minutes.

---

## 5. Load the inspection data (first backfill)

The first ETL run loads every inspection since 2022-01-01. Later runs only fetch the last 14 days and merge the changes.

```bash
gcloud run jobs execute food-etl --region us-central1 --wait
```

Check that it worked:

```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) AS rows, MIN(inspection_date) AS first, MAX(inspection_date) AS last
   FROM \`$PROJECT.food_safety.inspections\`"
bq query --use_legacy_sql=false \
  "SELECT * FROM \`$PROJECT.food_safety.etl_runs\` ORDER BY finished_at DESC LIMIT 3"
```

**Write down** the row count and the job's run time (Console → Cloud Run → Jobs → food-etl → the execution). They are resume numbers.

To backfill further back, run once with an earlier start date:

```bash
gcloud run jobs execute food-etl --region us-central1 --wait --args="--since=2018-07-01"
```

(July 2018 is when Chicago adopted the current food code and checklist numbering. Earlier violation numbers mean different things.)

---

## 6. Build the food code search index

Run this once from your laptop. It downloads the official Chicago Food Code Rules PDF, splits it by section, embeds each section with Vertex AI, and loads the result into BigQuery.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export GCP_PROJECT=$PROJECT

python scripts/ingest_food_code.py --dry-run   # chunk only: check the section count looks right
python scripts/ingest_food_code.py             # embed and load (a few minutes)
```

- The dry run should report several hundred chunks and print the first few. If it finds 0 sections, the PDF layout changed. Paste the dry-run output into our chat and the section pattern can be adjusted.
- If the download fails, save the PDF from <https://www.chicago.gov/content/dam/city/depts/dol/rulesandregs/CDPH-Food-Code-Rules-02-01-2019.pdf> and run `python scripts/ingest_food_code.py --pdf ./CDPH-Food-Code-Rules.pdf`.

---

## 7. Confirm the model ID

Gemini model names change over time. Open Console → **Vertex AI** → **Model Garden**, search "Gemini Flash", and note the current model ID. If it isn't `gemini-2.5-flash`, set it and re-apply:

```bash
cd infra/terraform
terraform apply -var="agent_model=<current-id>"
cd ../..
```

---

## 8. Open the app and ask questions

```bash
terraform -chdir=infra/terraform output app_url
```

Open the URL. You should see:

- a line saying which day the inspections run through
- the charts, filled with BigQuery data
- the question box: try the three suggested questions, and watch the "How it answered" column list each lookup as it runs

If something is wrong, read the logs:

```bash
gcloud run services logs read food-inspections --region us-central1 --limit 50
```

---

## 9. Run the evals and record the results

```bash
export GCP_PROJECT=$PROJECT DATA_BACKEND=bigquery
python -m evals.run_evals --list-sections | head -40    # which code sections were indexed
python -m evals.run_evals                               # full golden set, about 29 questions
```

Results go to `evals/results/latest.md` and `latest.json`. The run prints tool-choice accuracy, answer accuracy, retrieval recall, grounding rate, safety pass rate, and P50/P95 latency.

- If a **rules** question fails only on retrieval, compare its `expect_sections` in `evals/questions.json` with the `--list-sections` output. Chicago's numbering follows the FDA Food Code, but check each one.
- Fix real failures in the prompt or the tool descriptions (`backend/agent/loop.py`, `backend/agent/tools.py`), then run again. Keep notes on what changed and how the numbers moved. That before-and-after story is good interview material.

---

## 10. Turn on automatic deploys and evals (GitHub Actions)

In GitHub: **Settings** → **Secrets and variables** → **Actions**.

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `GCP_PROJECT` | your project ID |
| Variable | `GCP_REGION` | `us-central1` |
| Secret | `GCP_WORKLOAD_IDENTITY_PROVIDER` | `terraform output -raw workload_identity_provider` |
| Secret | `GCP_SERVICE_ACCOUNT` | `terraform output -raw deployer_service_account` |

After that:

- Every push to `main` builds the image, deploys it, and runs a smoke test (`.github/workflows/deploy.yml`).
- Every pull request that touches `backend/agent/` or `evals/` runs the eval suite and posts the score table on the run's summary page (`.github/workflows/agent-evals.yml`). It fails if accuracy drops below the thresholds in `evals/run_evals.py`.
- Unit tests and the frontend build run on every push, as before (`ci.yml`).

No service account key files are involved. GitHub proves its identity to Google with short-lived tokens, and the Terraform rule only accepts tokens from this repository.

---

## 11. Check the daily refresh

The scheduler starts the ETL at 6:15 a.m. Chicago time. To test it now: Console → **Cloud Scheduler** → `food-etl-daily` → **Force run**. Then:

```bash
bq query --use_legacy_sql=false \
  "SELECT run_id, finished_at, rows_fetched, rows_merged, status FROM \`$PROJECT.food_safety.etl_runs\` ORDER BY finished_at DESC LIMIT 5"
```

The date line at the top of the app should match the newest inspection.

---

## 12. Keep Railway working (optional)

The original PostgreSQL setup still works. `DATA_BACKEND` defaults to `postgres`. One change to know about: the frontend now calls the API at its **own origin** unless `VITE_API_URL` is set. The Railway frontend service already sets `VITE_API_URL`, so redeploying it works. Keep that variable. The agent box only works on the BigQuery deployment. On Railway it shows "The agent runs on the BigQuery backend."

Once the GCP version is live, point the "Live URL" in the README and on your resume at the Cloud Run URL.

---

## 13. Numbers to collect for your resume

Collect these before writing any bullet. Each one comes from a step above:

- Rows loaded on the first backfill, and the daily merge size (`etl_runs`)
- ETL run time (Cloud Run job execution details)
- Eval results: tool-choice accuracy, answer accuracy, retrieval recall, grounding rate, safety pass rate, P95 latency
- Any eval improvement you made, with before and after numbers
- Unit test count (`python -m unittest discover -s tests`)

Send them back in the chat and the resume bullets can be written from the real numbers.

---

## 14. Tear down

```bash
terraform -chdir=infra/terraform destroy
gcloud artifacts docker images list us-central1-docker.pkg.dev/$PROJECT/food-safety   # should be gone with the repo
```

Or delete the whole project: `gcloud projects delete $PROJECT`. Workload identity pools stay soft-deleted for 30 days, so re-creating one with the same name inside that window fails. Change `workload_identity_pool_id` if you rebuild soon after.

---

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `terraform apply` fails with SERVICE_DISABLED | APIs still turning on. Run apply again. |
| `gcloud builds submit` fails with PERMISSION_DENIED | Step 4's role grants for the build service account are missing. |
| Charts show "did not load" and `/health/db` returns 503 | The app's service account can't reach BigQuery, or the dataset is empty. Run step 5 and check the logs. |
| Agent says "not available right now" | Check the logs. Usually the model ID (step 7) or a missing Vertex AI permission. |
| Agent answers rules questions badly | The food code index is empty or stale. Run step 6. |
| `VECTOR_SEARCH` error in the logs | `food_code_chunks` is empty. Run step 6. |
| Scheduler shows 403 | The scheduler service account lacks invoker on the job. Re-run `terraform apply`. |
| ETL job times out on the first run | Raise `timeout` in `infra/terraform/run.tf`, or backfill a shorter range first with `--since`. |
