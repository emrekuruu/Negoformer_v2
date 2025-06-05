#!/bin/bash
set -e

echo "Step 2: Running data collection..."
python -u run.py tournament_configurations/data_collection.yaml | tee -a /app/bootstrap.log

echo "Step 3: Uploading results to S3..."
python upload_to_s3.py

echo "Pipeline completed successfully!"
