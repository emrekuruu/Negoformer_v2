#!/usr/bin/env python3
"""
S3 Folder Downloader Script
Downloads all files from an S3 bucket folder to a local directory.
Maintains folder structure and provides progress tracking.
"""

import os
import boto3
import csv
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict
from dotenv import load_dotenv
import sys

# Load environment variables from .env file
load_dotenv()

# Configuration - modify these values as needed
LOCAL_DOWNLOAD_PATH = "./results/sessions"  # Local directory to download files
CSV_OUTPUT_PATH = "./download_log.csv"  # Path for the download log CSV file
BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME')  # Set in .env file
S3_FOLDER_PATH = "sessions"  # Change this to your desired S3 folder path (empty string for root)

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
    
    def get_s3_file_list(self, s3_folder_path: str) -> List[Dict]:
        """
        Get list of all files in the S3 folder
        
        Args:
            s3_folder_path: Path to the folder in S3 bucket
            
        Returns:
            List of dictionaries containing file information
        """
        files_to_download = []
        
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
                                's3_key': obj['Key'],
                                'relative_path': relative_path,
                                'size': obj['Size'],
                                'last_modified': obj['LastModified'],
                                'size_mb': round(obj['Size'] / (1024 * 1024), 2)
                            }
                            files_to_download.append(file_info)
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Error: Bucket '{self.bucket_name}' does not exist.")
                raise
            else:
                print(f"Error listing S3 objects: {e}")
                raise
                
        return files_to_download
    
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """
        Download a single file from S3 to local path
        
        Args:
            s3_key: S3 object key
            local_path: Local file path to save the file
            
        Returns:
            True if download successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # Download the file
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            return True
            
        except Exception as e:
            print(f"Error downloading {s3_key}: {e}")
            return False
    
    def write_download_log(self, download_results: List[Dict], csv_output_path: str) -> bool:
        """
        Write download results to a CSV log file
        
        Args:
            download_results: List of download result dictionaries
            csv_output_path: Path to save the CSV log file
            
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
                'relative_path',
                's3_key',
                'local_path',
                'size_bytes',
                'size_mb',
                'last_modified',
                'download_status',
                'download_time'
            ]
            
            with open(csv_output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(download_results)
            
            return True
        except Exception as e:
            print(f"Error writing CSV log file: {e}")
            return False
    
    def download_folder(self, s3_folder_path: str = '', local_download_path: str = './downloaded_files', 
                       csv_output_path: str = './download_log.csv') -> dict:
        """
        Download entire S3 folder to local directory
        
        Args:
            s3_folder_path: Source folder path in S3 bucket (empty string for root)
            local_download_path: Local directory path to download files
            csv_output_path: Path to save the download log CSV file
            
        Returns:
            Dictionary with download statistics
        """
        print(f"Starting download from s3://{self.bucket_name}/{s3_folder_path}")
        print(f"Local download path: {local_download_path}")
        
        # Get list of files to download
        print("Scanning S3 files...")
        files_to_download = self.get_s3_file_list(s3_folder_path)
        print(f"Found {len(files_to_download)} files to download")
        
        if not files_to_download:
            print("No files found to download.")
            return {
                'total_files': 0,
                'successful_downloads': 0,
                'failed_downloads': 0,
                'total_size_mb': 0,
                'csv_created': False
            }
        
        # Calculate total size
        total_size_bytes = sum(file_info['size'] for file_info in files_to_download)
        total_size_mb = round(total_size_bytes / (1024 * 1024), 2)
        total_size_gb = round(total_size_mb / 1024, 2)
        
        print(f"Total size to download: {total_size_mb} MB ({total_size_gb} GB)")
        print("\nStarting downloads...")
        
        # Download files
        download_results = []
        successful_downloads = 0
        failed_downloads = 0
        
        for i, file_info in enumerate(files_to_download, 1):
            s3_key = file_info['s3_key']
            relative_path = file_info['relative_path']
            local_file_path = os.path.join(local_download_path, relative_path)
            
            print(f"[{i}/{len(files_to_download)}] Downloading: {relative_path} ({file_info['size_mb']} MB)")
            
            # Download the file
            download_start_time = datetime.now()
            download_success = self.download_file(s3_key, local_file_path)
            download_end_time = datetime.now()
            
            # Record download result
            download_result = {
                'relative_path': relative_path,
                's3_key': s3_key,
                'local_path': local_file_path,
                'size_bytes': file_info['size'],
                'size_mb': file_info['size_mb'],
                'last_modified': file_info['last_modified'].isoformat(),
                'download_status': 'SUCCESS' if download_success else 'FAILED',
                'download_time': download_end_time.isoformat()
            }
            download_results.append(download_result)
            
            if download_success:
                successful_downloads += 1
                print(f"  ✓ Downloaded successfully")
            else:
                failed_downloads += 1
                print(f"  ✗ Download failed")
        
        # Write download log
        print(f"\nWriting download log to '{csv_output_path}'...")
        csv_created = self.write_download_log(download_results, csv_output_path)
        
        # Summary
        stats = {
            'total_files': len(files_to_download),
            'successful_downloads': successful_downloads,
            'failed_downloads': failed_downloads,
            'total_size_mb': total_size_mb,
            'total_size_gb': total_size_gb,
            'csv_created': csv_created,
            'csv_path': csv_output_path,
            'local_path': local_download_path
        }
        
        print(f"\n--- Download Summary ---")
        print(f"Total files: {stats['total_files']}")
        print(f"Successful downloads: {stats['successful_downloads']}")
        print(f"Failed downloads: {stats['failed_downloads']}")
        print(f"Total size downloaded: {stats['total_size_mb']} MB ({stats['total_size_gb']} GB)")
        print(f"Files saved to: {local_download_path}")
        print(f"Download log: {csv_output_path if csv_created else 'Failed to create'}")
        
        return stats


def main():
    # Validate configuration
    if not BUCKET_NAME:
        print("Error: AWS_S3_BUCKET_NAME environment variable is required.")
        print("Please set it in your .env file or environment.")
        return
    
    try:
        # Initialize downloader
        downloader = S3FolderDownloader(bucket_name=BUCKET_NAME)
        
        # Confirm download
        print(f"This will download all files from s3://{BUCKET_NAME}/{S3_FOLDER_PATH}")
        print(f"to local directory: {LOCAL_DOWNLOAD_PATH}")
        
        confirm = input("\nDo you want to proceed? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Download cancelled.")
            return
        
        # Start download
        stats = downloader.download_folder(
            s3_folder_path=S3_FOLDER_PATH,
            local_download_path=LOCAL_DOWNLOAD_PATH,
            csv_output_path=CSV_OUTPUT_PATH
        )
        
        if stats['successful_downloads'] > 0:
            print(f"\nDownload completed! {stats['successful_downloads']} files downloaded successfully.")
            if stats['failed_downloads'] > 0:
                print(f"Warning: {stats['failed_downloads']} files failed to download.")
        else:
            print("\nNo files were downloaded successfully.")
            
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please provide credentials via:")
        print("1. Environment variables in .env file (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
        print("2. AWS credentials file (~/.aws/credentials)")
        print("3. IAM role (if running on EC2)")
        
    except KeyboardInterrupt:
        print("\nDownload interrupted by user.")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main() 