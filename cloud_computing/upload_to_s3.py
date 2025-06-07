#!/usr/bin/env python3
"""
S3 Folder Upload Script
Uploads a local folder to S3 bucket without overriding existing files.
Only adds new files that don't already exist in the target S3 location.
"""

import os
import boto3
import argparse
from pathlib import Path
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Set, List
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables from .env file
load_dotenv()

# Configuration - modify these values as needed
LOCAL_FOLDER_PATH = "./results/data_collection/sessions"  # Change this to your desired folder path
BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME')  # Set in .env file
S3_FOLDER_PATH = "sessions"  # Change this to your desired S3 folder path (empty string for root)

class S3FolderUploader:
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
    
    def get_existing_s3_files(self, s3_folder_path: str) -> Set[str]:
        """
        Get list of existing files in the S3 folder
        
        Args:
            s3_folder_path: Path to the folder in S3 bucket
            
        Returns:
            Set of existing file keys in S3
        """
        existing_files = set()
        
        try:
            # Ensure folder path ends with '/' for proper prefix matching
            if s3_folder_path and not s3_folder_path.endswith('/'):
                s3_folder_path += '/'
            
            paginator = self.s3_client.get_paginator('list_objects_v2')
            
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=s3_folder_path):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        existing_files.add(obj['Key'])
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Error: Bucket '{self.bucket_name}' does not exist.")
                raise
            else:
                print(f"Error listing S3 objects: {e}")
                raise
                
        return existing_files
    
    def get_local_files(self, local_folder_path: str) -> List[str]:
        """
        Get list of all files in the local folder recursively
        
        Args:
            local_folder_path: Path to the local folder
            
        Returns:
            List of relative file paths from the local folder
        """
        local_files = []
        local_path = Path(local_folder_path)
        
        if not local_path.exists():
            raise FileNotFoundError(f"Local folder '{local_folder_path}' does not exist.")
        
        if not local_path.is_dir():
            raise NotADirectoryError(f"'{local_folder_path}' is not a directory.")
        
        for file_path in local_path.rglob('*'):
            if file_path.is_file():
                # Get relative path from the local folder
                relative_path = file_path.relative_to(local_path)
                local_files.append(str(relative_path))
        
        return local_files
    
    def upload_file(self, local_file_path: str, s3_key: str) -> bool:
        """
        Upload a single file to S3
        
        Args:
            local_file_path: Path to the local file
            s3_key: S3 key (path) for the file
            
        Returns:
            True if upload successful, False otherwise
        """
        try:
            self.s3_client.upload_file(local_file_path, self.bucket_name, s3_key)
            return True
        except ClientError as e:
            print(f"Error uploading {local_file_path}: {e}")
            return False
    
    def upload_folder(self, local_folder_path: str, s3_folder_path: str = '', 
                     dry_run: bool = False) -> dict:
        """
        Upload local folder to S3 without overriding existing files
        
        Args:
            local_folder_path: Path to the local folder to upload
            s3_folder_path: Target folder path in S3 bucket (empty string for root)
            dry_run: If True, only show what would be uploaded without actually uploading
            
        Returns:
            Dictionary with upload statistics
        """
        print(f"Starting upload from '{local_folder_path}' to s3://{self.bucket_name}/{s3_folder_path}")
        
        # Get existing files in S3
        print("Checking existing files in S3...")
        existing_s3_files = self.get_existing_s3_files(s3_folder_path)
        print(f"Found {len(existing_s3_files)} existing files in S3")
        
        # Get local files
        print("Scanning local files...")
        local_files = self.get_local_files(local_folder_path)
        print(f"Found {len(local_files)} files in local folder")
        
        # Determine files to upload
        files_to_upload = []
        skipped_files = []
        
        for local_file in local_files:
            # Construct S3 key
            if s3_folder_path:
                s3_key = f"{s3_folder_path.rstrip('/')}/{local_file}"
            else:
                s3_key = local_file
            
            # Convert Windows paths to Unix-style for S3
            s3_key = s3_key.replace('\\', '/')
            
            if s3_key in existing_s3_files:
                skipped_files.append(local_file)
            else:
                files_to_upload.append((local_file, s3_key))
        
        # Upload files
        successful_uploads = 0
        failed_uploads = 0
        
        if dry_run:
            print(f"\nDry run: Would upload {len(files_to_upload)} new files")
            if files_to_upload:
                print("Files that would be uploaded:")
                for local_file, s3_key in files_to_upload[:10]:  # Show first 10 as example
                    print(f"  {local_file} -> s3://{self.bucket_name}/{s3_key}")
                if len(files_to_upload) > 10:
                    print(f"  ... and {len(files_to_upload) - 10} more files")
        elif files_to_upload:
            print(f"\nUploading {len(files_to_upload)} new files...")
            
            # Create progress bar
            progress_bar = tqdm(files_to_upload, desc="Uploading files", unit="file")
            
            for local_file, s3_key in progress_bar:
                # Update progress bar description with current file
                progress_bar.set_description(f"Uploading: {local_file[:50]}{'...' if len(local_file) > 50 else ''}")
                
                local_file_path = os.path.join(local_folder_path, local_file)
                
                if self.upload_file(local_file_path, s3_key):
                    successful_uploads += 1
                else:
                    failed_uploads += 1
                    # Only print error messages
                    print(f"\n✗ Failed to upload: {local_file}")
            
            progress_bar.close()
        
        # Summary
        stats = {
            'total_local_files': len(local_files),
            'existing_s3_files': len(existing_s3_files),
            'files_to_upload': len(files_to_upload),
            'skipped_files': len(skipped_files),
            'successful_uploads': successful_uploads,
            'failed_uploads': failed_uploads
        }
        
        print(f"\n--- Upload Summary ---")
        print(f"Total local files: {stats['total_local_files']}")
        print(f"Existing S3 files: {stats['existing_s3_files']}")
        print(f"Files to upload: {stats['files_to_upload']}")
        print(f"Skipped files: {stats['skipped_files']}")
        if not dry_run:
            print(f"Successful uploads: {stats['successful_uploads']}")
            print(f"Failed uploads: {stats['failed_uploads']}")
        
        return stats


def main():
    parser = argparse.ArgumentParser(description='Upload local folder to S3 without overriding existing files')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded without actually uploading')
    parser.add_argument('--region', help='AWS region (overrides AWS_DEFAULT_REGION env var)')
    
    args = parser.parse_args()
    
    # Validate configuration
    if not BUCKET_NAME:
        print("Error: AWS_S3_BUCKET_NAME environment variable is required.")
        print("Please set it in your .env file or environment.")
        return
    
    try:
        # Initialize uploader
        uploader = S3FolderUploader(
            bucket_name=BUCKET_NAME,
            region_name=args.region
        )
        
        # Upload folder
        stats = uploader.upload_folder(
            local_folder_path=LOCAL_FOLDER_PATH,
            s3_folder_path=S3_FOLDER_PATH,
            dry_run=args.dry_run
        )
        
        if args.dry_run:
            print("\nThis was a dry run. Use without --dry-run to actually upload files.")
        else:
            print(f"\nUpload completed! {stats['successful_uploads']} files uploaded successfully.")
            
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please provide credentials via:")
        print("1. Environment variables in .env file (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
        print("2. AWS credentials file (~/.aws/credentials)")
        print("3. IAM role (if running on EC2)")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main() 