#!/bin/bash
set -e

echo "Step 1: Creating file index..."
python cloud_computing/get_indexed_files_in_s3.py

echo "Step 2: Running data collection..."
python -u run.py tournament_configurations/data_collection.yaml | tee -a /app/bootstrap.log

echo "Step 3: Uploading results to S3..."
python cloud_computing/upload_to_s3.py

echo "Step 4: Self-terminating pod..."
runpodctl remove pod "$RUNPOD_POD_ID"

echo "Pipeline completed successfully!"
