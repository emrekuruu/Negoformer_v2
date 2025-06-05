#!/usr/bin/env python3
"""
S3 File Indexer Script
Creates a CSV index of files in S3 bucket without downloading the actual content.
Generates a CSV file with file information including name, size, and last modified date.
"""

import os
import boto3
import csv
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration - modify these values as needed
CSV_OUTPUT_PATH = "./indexed_files.csv"  # Path for the output CSV file
BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME')  # Set in .env file
S3_FOLDER_PATH = "results"  # Change this to your desired S3 folder path (empty string for root)

class S3FileIndexer:
    def __init__(self, bucket_name: str, region_name: str = None):
        """
        Initialize S3 client using environment variables
        
        Args:
            bucket_name: Name of the S3 bucket
            region_name: AWS region name (will use AWS_DEFAULT_REGION env var if not provided)
        """
        self.bucket_name = bucket_name
        
        # Get AWS credentials and region from environment variables
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        region = region_name or os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
        
        # Initialize S3 client
        if aws_access_key_id and aws_secret_access_key:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region
            )
        else:
            # Use default credentials (IAM role, etc.)
            self.s3_client = boto3.client('s3', region_name=region)
    
    def get_s3_file_details(self, s3_folder_path: str) -> List[Dict]:
        """
        Get detailed information about all files in the S3 folder
        
        Args:
            s3_folder_path: Path to the folder in S3 bucket
            
        Returns:
            List of dictionaries containing file details
        """
        file_details = []
        
        try:
            # Ensure folder path ends with '/' for proper prefix matching
            if s3_folder_path and not s3_folder_path.endswith('/'):
                s3_folder_path += '/'
            
            paginator = self.s3_client.get_paginator('list_objects_v2')
            
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=s3_folder_path):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        # Skip folders (keys ending with '/')
                        if not obj['Key'].endswith('/'):
                            # Calculate relative path from the S3 folder
                            relative_path = obj['Key']
                            if s3_folder_path:
                                s3_prefix = s3_folder_path.rstrip('/') + '/'
                                if obj['Key'].startswith(s3_prefix):
                                    relative_path = obj['Key'][len(s3_prefix):]
                            
                            file_info = {
                                'relative_path': os.path.basename(obj['Key'])
                            }
                            file_details.append(file_info)
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Error: Bucket '{self.bucket_name}' does not exist.")
                raise
            else:
                print(f"Error listing S3 objects: {e}")
                raise
                
        return file_details
    
    def write_csv_index(self, file_details: List[Dict], csv_output_path: str) -> bool:
        """
        Write file details to a CSV file
        
        Args:
            file_details: List of file detail dictionaries
            csv_output_path: Path to save the CSV file
            
        Returns:
            True if CSV creation successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            csv_dir = os.path.dirname(csv_output_path)
            if csv_dir:
                os.makedirs(csv_dir, exist_ok=True)
            
            # Define CSV headers
            headers = [
                'relative_path'
            ]
            
            with open(csv_output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(file_details)
            
            return True
        except Exception as e:
            print(f"Error writing CSV file: {e}")
            return False
    
    def create_file_index(self, s3_folder_path: str = '', csv_output_path: str = './indexed_files.csv') -> dict:
        """
        Create a CSV index of files in S3 folder without downloading them
        
        Args:
            s3_folder_path: Source folder path in S3 bucket (empty string for root)
            csv_output_path: Path to save the CSV index file
            
        Returns:
            Dictionary with indexing statistics
        """
        print(f"Creating file index from s3://{self.bucket_name}/{s3_folder_path}")
        
        # Get file details from S3
        print("Scanning S3 files...")
        file_details = self.get_s3_file_details(s3_folder_path)
        print(f"Found {len(file_details)} files in S3")
        
        if not file_details:
            print("No files found to index.")
            return {
                'total_files': 0,
                'csv_created': False,
                'csv_path': csv_output_path,
                'total_size_mb': 0
            }
        
        # Write CSV index
        print(f"Writing CSV index to '{csv_output_path}'...")
        csv_created = self.write_csv_index(file_details, csv_output_path)
        
        # Display sample of files found
        print(f"\nSample of files found:")
        for i, file_info in enumerate(file_details[:5]):  # Show first 5 files
            print(f"  {i+1}. {file_info['relative_path']}")
        
        if len(file_details) > 5:
            print(f"  ... and {len(file_details) - 5} more files")
        
        # Summary
        stats = {
            'total_files': len(file_details),
            'csv_created': csv_created,
            'csv_path': csv_output_path,
            'total_size_mb': 0,
            'total_size_gb': 0
        }
        
        print(f"\n--- Indexing Summary ---")
        print(f"Total files indexed: {stats['total_files']}")
        print(f"CSV file created: {csv_output_path if csv_created else 'Failed'}")
        
        return stats


def main():
    # Validate configuration
    if not BUCKET_NAME:
        print("Error: AWS_S3_BUCKET_NAME environment variable is required.")
        print("Please set it in your .env file or environment.")
        return
    
    try:
        # Initialize indexer
        indexer = S3FileIndexer(bucket_name=BUCKET_NAME)
        
        # Create file index
        stats = indexer.create_file_index(
            s3_folder_path=S3_FOLDER_PATH,
            csv_output_path=CSV_OUTPUT_PATH
        )
        
        if stats['csv_created']:
            print(f"\nFile index completed! CSV saved to: {stats['csv_path']}")
            print(f"Total of {stats['total_files']} files indexed")
        else:
            print("\nError: Failed to create CSV file.")
            
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please provide credentials via:")
        print("1. Environment variables in .env file (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
        print("2. AWS credentials file (~/.aws/credentials)")
        print("3. IAM role (if running on EC2)")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main() 