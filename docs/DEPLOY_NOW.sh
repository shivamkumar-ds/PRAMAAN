#!/usr/bin/env bash
# PRAMAAN deployment — run this on YOUR machine (gcloud + vercel already
# authenticated there), NOT inside any sandboxed agent environment.
#
# Fill in: PROJECT_ID, REGION, REAL_PASSWORD, YOUR_OPENAI_KEY before running.
# Adapted from docs/DEPLOYMENT.md (Cloud Run + Cloud SQL + Vercel), using
# this repo's actual pramaan/pramaan naming -- not the obsolete bidops one.
set -euo pipefail

PROJECT_ID="your-gcp-project-id"
REGION="asia-south1"           # or your preferred region
REAL_PASSWORD="CHANGE_ME"
OPENAI_KEY="CHANGE_ME"

echo "== 0. Auth (run once, opens a browser on YOUR machine) =="
gcloud auth login
gcloud config set project "$PROJECT_ID"

echo "== 1. Enable APIs + Artifact Registry =="
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com
gcloud artifacts repositories create pramaan --repository-format=docker --location="$REGION" || true

echo "== 2. Cloud SQL: pramaan/pramaan (matches docker-compose.yml) =="
gcloud sql instances create pramaan-db --database-version=POSTGRES_16 \
  --tier=db-g1-small --region="$REGION" || true
gcloud sql databases create pramaan --instance=pramaan-db || true
gcloud sql users create pramaan --instance=pramaan-db --password="$REAL_PASSWORD" || true

echo "== 3. Secrets =="
printf 'postgresql+psycopg2://pramaan:%s@/pramaan?host=/cloudsql/%s:%s:pramaan-db' \
  "$REAL_PASSWORD" "$PROJECT_ID" "$REGION" | gcloud secrets create pramaan-database-url --data-file=- || true
python3 -c "import secrets; print(secrets.token_hex(32))" | gcloud secrets create pramaan-jwt-secret --data-file=- || true
printf '%s' "$OPENAI_KEY" | gcloud secrets create pramaan-openai-key --data-file=- || true

echo "== 4. Build backend image =="
cd backend
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/pramaan/backend:latest"

echo "== 5. Run migrations (Cloud Run Job, BEFORE deploying the service) =="
gcloud run jobs create pramaan-migrate \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/pramaan/backend:latest" --region="$REGION" \
  --set-secrets=DATABASE_URL=pramaan-database-url:latest \
  --set-cloudsql-instances="$PROJECT_ID:$REGION:pramaan-db" \
  --command=/app/scripts/migrate.sh || true
gcloud run jobs execute pramaan-migrate --region="$REGION" --wait

echo "== 6. Seed demo/registry data (uses backend/scripts/seed_demo.py) =="
gcloud run jobs create pramaan-seed \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/pramaan/backend:latest" --region="$REGION" \
  --set-secrets=DATABASE_URL=pramaan-database-url:latest \
  --set-cloudsql-instances="$PROJECT_ID:$REGION:pramaan-db" \
  --command=python --args=-m,scripts.seed_demo || true
gcloud run jobs execute pramaan-seed --region="$REGION" --wait

echo "== 7. Deploy backend service =="
gcloud run deploy pramaan-api \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/pramaan/backend:latest" --region="$REGION" \
  --allow-unauthenticated --max-instances=1 \
  --add-cloudsql-instances="$PROJECT_ID:$REGION:pramaan-db" \
  --set-secrets=DATABASE_URL=pramaan-database-url:latest,SECRET_KEY=pramaan-jwt-secret:latest,OPENAI_API_KEY=pramaan-openai-key:latest \
  --set-env-vars=APP_ENV=production,LLM_PROVIDER=openai,STORAGE_BACKEND=local

BACKEND_URL=$(gcloud run services describe pramaan-api --region="$REGION" --format='value(status.url)')
echo "Backend deployed at: $BACKEND_URL"

echo "== 8. Frontend: Vercel =="
cd ../frontend
echo "VITE_API_BASE_URL=$BACKEND_URL" > .env.production
vercel login   # if not already logged in
vercel --prod
# Grab the printed production URL, then:
FRONTEND_URL="https://REPLACE-WITH-YOUR-VERCEL-URL.vercel.app"

echo "== 9. Lock CORS down to the real frontend URL =="
gcloud run services update pramaan-api --region="$REGION" \
  --set-env-vars=APP_ENV=production,LLM_PROVIDER=openai,STORAGE_BACKEND=local,ALLOWED_ORIGINS="$FRONTEND_URL"

echo "== 10. Verify =="
curl -s "$BACKEND_URL/health"
curl -s "$BACKEND_URL/health/db"
echo "Now open $FRONTEND_URL and run the real workflow."
