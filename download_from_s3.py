#!/usr/bin/env python3
"""
S3 Folder Download Script
Downloads files from S3 bucket to local folder without overriding existing files.
Only downloads new files that don't already exist in the target local location.
"""

import os
import boto3
import argparse
from pathlib import Path
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Set, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration - modify these values as needed
LOCAL_FOLDER_PATH = "./results"  # Change this to your desired local folder path
BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME')  # Set in .env file
S3_FOLDER_PATH = "results"  # Change this to your desired S3 folder path (empty string for root)

class S3FolderDownloader:
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
    
    def get_s3_files(self, s3_folder_path: str) -> List[str]:
        """
        Get list of all files in the S3 folder
        
        Args:
            s3_folder_path: Path to the folder in S3 bucket
            
        Returns:
            List of S3 file keys
        """
        s3_files = []
        
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
                            s3_files.append(obj['Key'])
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Error: Bucket '{self.bucket_name}' does not exist.")
                raise
            else:
                print(f"Error listing S3 objects: {e}")
                raise
                
        return s3_files
    
    def get_existing_local_files(self, local_folder_path: str) -> Set[str]:
        """
        Get list of existing files in the local folder recursively
        
        Args:
            local_folder_path: Path to the local folder
            
        Returns:
            Set of relative file paths from the local folder
        """
        existing_files = set()
        local_path = Path(local_folder_path)
        
        if local_path.exists() and local_path.is_dir():
            for file_path in local_path.rglob('*'):
                if file_path.is_file():
                    # Get relative path from the local folder
                    relative_path = file_path.relative_to(local_path)
                    # Convert to Unix-style path for consistency
                    existing_files.add(str(relative_path).replace('\\', '/'))
        
        return existing_files
    
    def download_file(self, s3_key: str, local_file_path: str) -> bool:
        """
        Download a single file from S3
        
        Args:
            s3_key: S3 key (path) for the file
            local_file_path: Path to save the local file
            
        Returns:
            True if download successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            local_dir = os.path.dirname(local_file_path)
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)
            
            self.s3_client.download_file(self.bucket_name, s3_key, local_file_path)
            return True
        except ClientError as e:
            print(f"Error downloading {s3_key}: {e}")
            return False
    
    def download_folder(self, s3_folder_path: str = '', local_folder_path: str = './downloads',
                       dry_run: bool = False) -> dict:
        """
        Download S3 folder to local directory without overriding existing files
        
        Args:
            s3_folder_path: Source folder path in S3 bucket (empty string for root)
            local_folder_path: Path to the local folder to download to
            dry_run: If True, only show what would be downloaded without actually downloading
            
        Returns:
            Dictionary with download statistics
        """
        print(f"Starting download from s3://{self.bucket_name}/{s3_folder_path} to '{local_folder_path}'")
        
        # Get files in S3
        print("Scanning S3 files...")
        s3_files = self.get_s3_files(s3_folder_path)
        print(f"Found {len(s3_files)} files in S3")
        
        # Get existing local files
        print("Checking existing local files...")
        existing_local_files = self.get_existing_local_files(local_folder_path)
        print(f"Found {len(existing_local_files)} existing files in local folder")
        
        # Determine files to download
        files_to_download = []
        skipped_files = []
        
        for s3_key in s3_files:
            # Determine local relative path
            if s3_folder_path:
                # Remove the S3 folder prefix to get the relative path
                s3_prefix = s3_folder_path.rstrip('/') + '/'
                if s3_key.startswith(s3_prefix):
                    relative_path = s3_key[len(s3_prefix):]
                else:
                    relative_path = s3_key
            else:
                relative_path = s3_key
            
            # Convert to Unix-style path for comparison
            relative_path_normalized = relative_path.replace('\\', '/')
            
            if relative_path_normalized in existing_local_files:
                skipped_files.append(relative_path)
                print(f"SKIP: {relative_path} (already exists locally)")
            else:
                files_to_download.append((s3_key, relative_path))
                if dry_run:
                    print(f"WOULD DOWNLOAD: s3://{self.bucket_name}/{s3_key} -> {relative_path}")
                else:
                    print(f"DOWNLOAD: s3://{self.bucket_name}/{s3_key} -> {relative_path}")
        
        # Download files
        successful_downloads = 0
        failed_downloads = 0
        
        if not dry_run and files_to_download:
            print(f"\nDownloading {len(files_to_download)} new files...")
            
            for s3_key, relative_path in files_to_download:
                local_file_path = os.path.join(local_folder_path, relative_path)
                
                if self.download_file(s3_key, local_file_path):
                    successful_downloads += 1
                else:
                    failed_downloads += 1
        
        # Summary
        stats = {
            'total_s3_files': len(s3_files),
            'existing_local_files': len(existing_local_files),
            'files_to_download': len(files_to_download),
            'skipped_files': len(skipped_files),
            'successful_downloads': successful_downloads,
            'failed_downloads': failed_downloads
        }
        
        print(f"\n--- Download Summary ---")
        print(f"Total S3 files: {stats['total_s3_files']}")
        print(f"Existing local files: {stats['existing_local_files']}")
        print(f"Files to download: {stats['files_to_download']}")
        print(f"Skipped files: {stats['skipped_files']}")
        if not dry_run:
            print(f"Successful downloads: {stats['successful_downloads']}")
            print(f"Failed downloads: {stats['failed_downloads']}")
        
        return stats


def main():
    parser = argparse.ArgumentParser(description='Download files from S3 folder to local directory without overriding existing files')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be downloaded without actually downloading')
    parser.add_argument('--region', help='AWS region (overrides AWS_DEFAULT_REGION env var)')
    
    args = parser.parse_args()
    
    # Validate configuration
    if not BUCKET_NAME:
        print("Error: AWS_S3_BUCKET_NAME environment variable is required.")
        print("Please set it in your .env file or environment.")
        return
    
    try:
        # Initialize downloader
        downloader = S3FolderDownloader(
            bucket_name=BUCKET_NAME,
            region_name=args.region
        )
        
        # Download folder
        stats = downloader.download_folder(
            s3_folder_path=S3_FOLDER_PATH,
            local_folder_path=LOCAL_FOLDER_PATH,
            dry_run=args.dry_run
        )
        
        if args.dry_run:
            print("\nThis was a dry run. Use without --dry-run to actually download files.")
        else:
            print(f"\nDownload completed! {stats['successful_downloads']} files downloaded successfully.")
            
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please provide credentials via:")
        print("1. Environment variables in .env file (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
        print("2. AWS credentials file (~/.aws/credentials)")
        print("3. IAM role (if running on EC2)")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main() 