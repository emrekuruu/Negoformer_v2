#!/usr/bin/env python3
"""
S3 File Cleaner Script
Deletes files from S3 bucket that match specific patterns in their filenames.
Specifically targets files containing "NiceTitForTat" or "Caduceus".
"""

import os
import boto3
import csv
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict
from dotenv import load_dotenv
import re

# Load environment variables from .env file
load_dotenv()

CSV_OUTPUT_PATH = "./deletion_log.csv"  # Path for the deletion log CSV file
BUCKET_NAME = os.getenv('AWS_S3_BUCKET_NAME')  # Set in .env file
S3_FOLDER_PATH = "sessions"  # Change this to your desired S3 folder path (empty string for root)

# Patterns to match for deletion
DELETE_PATTERNS = [
    "NiceTitForTat",
    "Caduceus"
]

class S3FileCleaner:
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
    
    def get_s3_files_to_delete(self, s3_folder_path: str, patterns: List[str]) -> List[Dict]:
        """
        Get list of files in S3 folder that match deletion patterns
        
        Args:
            s3_folder_path: Path to the folder in S3 bucket
            patterns: List of patterns to match in filenames
            
        Returns:
            List of dictionaries containing file information for files to delete
        """
        files_to_delete = []
        
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
                            # Get just the filename from the full key
                            filename = os.path.basename(obj['Key'])
                            
                            # Check if filename contains any of the patterns
                            should_delete = False
                            matched_pattern = None
                            for pattern in patterns:
                                if pattern in filename:
                                    should_delete = True
                                    matched_pattern = pattern
                                    break
                            
                            if should_delete:
                                # Calculate relative path from the S3 folder
                                relative_path = obj['Key']
                                if s3_folder_path:
                                    s3_prefix = s3_folder_path.rstrip('/') + '/'
                                    if obj['Key'].startswith(s3_prefix):
                                        relative_path = obj['Key'][len(s3_prefix):]
                                
                                file_info = {
                                    's3_key': obj['Key'],
                                    'filename': filename,
                                    'relative_path': relative_path,
                                    'size': obj['Size'],
                                    'last_modified': obj['LastModified'],
                                    'size_mb': round(obj['Size'] / (1024 * 1024), 2),
                                    'matched_pattern': matched_pattern
                                }
                                files_to_delete.append(file_info)
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Error: Bucket '{self.bucket_name}' does not exist.")
                raise
            else:
                print(f"Error listing S3 objects: {e}")
                raise
                
        return files_to_delete
    
    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a single file from S3
        
        Args:
            s3_key: S3 object key to delete
            
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
            
        except Exception as e:
            print(f"Error deleting {s3_key}: {e}")
            return False
    
    def write_deletion_log(self, deletion_results: List[Dict], csv_output_path: str) -> bool:
        """
        Write deletion results to a CSV log file
        
        Args:
            deletion_results: List of deletion result dictionaries
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
                'filename',
                'relative_path',
                's3_key',
                'matched_pattern',
                'size_bytes',
                'size_mb',
                'last_modified',
                'deletion_status',
                'deletion_time'
            ]
            
            with open(csv_output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(deletion_results)
            
            return True
        except Exception as e:
            print(f"Error writing CSV log file: {e}")
            return False
    
    def clean_files(self, s3_folder_path: str = '', patterns: List[str] = None, 
                   csv_output_path: str = './deletion_log.csv') -> dict:
        """
        Delete files from S3 folder that match specified patterns
        
        Args:
            s3_folder_path: Source folder path in S3 bucket (empty string for root)
            patterns: List of patterns to match for deletion
            csv_output_path: Path to save the deletion log CSV file
            
        Returns:
            Dictionary with deletion statistics
        """
        if patterns is None:
            patterns = DELETE_PATTERNS
            
        print(f"Scanning for files to delete in s3://{self.bucket_name}/{s3_folder_path}")
        print(f"Patterns to match: {', '.join(patterns)}")
        
        # Get list of files to delete
        print("\nScanning S3 files...")
        files_to_delete = self.get_s3_files_to_delete(s3_folder_path, patterns)
        print(f"Found {len(files_to_delete)} files matching deletion patterns")
        
        if not files_to_delete:
            print("No files found matching deletion patterns.")
            return {
                'total_files_scanned': 0,
                'files_to_delete': 0,
                'successful_deletions': 0,
                'failed_deletions': 0,
                'total_size_deleted_mb': 0,
                'csv_created': False
            }
        
        # Show files that will be deleted
        print(f"\n--- FILES TO BE DELETED ---")
        total_size_bytes = 0
        for file_info in files_to_delete:
            print(f"  {file_info['filename']} ({file_info['size_mb']} MB) - matches '{file_info['matched_pattern']}'")
            total_size_bytes += file_info['size']
        
        total_size_mb = round(total_size_bytes / (1024 * 1024), 2)
        total_size_gb = round(total_size_mb / 1024, 2)
        
        print(f"\nTotal files to delete: {len(files_to_delete)}")
        print(f"Total size to delete: {total_size_mb} MB ({total_size_gb} GB)")
        
        # Double confirmation for safety
        print(f"\n⚠️  WARNING: This will PERMANENTLY DELETE {len(files_to_delete)} files from S3!")
        print("This action cannot be undone.")
        
        confirm1 = input("\nAre you sure you want to delete these files? (type 'DELETE' to confirm): ").strip()
        if confirm1 != 'DELETE':
            print("Deletion cancelled.")
            return {
                'total_files_scanned': 0,
                'files_to_delete': len(files_to_delete),
                'successful_deletions': 0,
                'failed_deletions': 0,
                'total_size_deleted_mb': 0,
                'csv_created': False,
                'cancelled': True
            }
        
        confirm2 = input("Final confirmation - type 'YES' to proceed with deletion: ").strip()
        if confirm2 != 'YES':
            print("Deletion cancelled.")
            return {
                'total_files_scanned': 0,
                'files_to_delete': len(files_to_delete),
                'successful_deletions': 0,
                'failed_deletions': 0,
                'total_size_deleted_mb': 0,
                'csv_created': False,
                'cancelled': True
            }
        
        print("\nStarting deletions...")
        
        # Delete files
        deletion_results = []
        successful_deletions = 0
        failed_deletions = 0
        total_deleted_size = 0
        
        for i, file_info in enumerate(files_to_delete, 1):
            s3_key = file_info['s3_key']
            filename = file_info['filename']
            
            print(f"[{i}/{len(files_to_delete)}] Deleting: {filename}")
            
            # Delete the file
            deletion_time = datetime.now()
            deletion_success = self.delete_file(s3_key)
            
            # Record deletion result
            deletion_result = {
                'filename': filename,
                'relative_path': file_info['relative_path'],
                's3_key': s3_key,
                'matched_pattern': file_info['matched_pattern'],
                'size_bytes': file_info['size'],
                'size_mb': file_info['size_mb'],
                'last_modified': file_info['last_modified'].isoformat(),
                'deletion_status': 'SUCCESS' if deletion_success else 'FAILED',
                'deletion_time': deletion_time.isoformat()
            }
            deletion_results.append(deletion_result)
            
            if deletion_success:
                successful_deletions += 1
                total_deleted_size += file_info['size']
                print(f"  ✓ Deleted successfully")
            else:
                failed_deletions += 1
                print(f"  ✗ Deletion failed")
        
        # Write deletion log
        print(f"\nWriting deletion log to '{csv_output_path}'...")
        csv_created = self.write_deletion_log(deletion_results, csv_output_path)
        
        # Summary
        total_deleted_mb = round(total_deleted_size / (1024 * 1024), 2)
        total_deleted_gb = round(total_deleted_mb / 1024, 2)
        
        stats = {
            'files_to_delete': len(files_to_delete),
            'successful_deletions': successful_deletions,
            'failed_deletions': failed_deletions,
            'total_size_deleted_mb': total_deleted_mb,
            'total_size_deleted_gb': total_deleted_gb,
            'csv_created': csv_created,
            'csv_path': csv_output_path
        }
        
        print(f"\n--- Deletion Summary ---")
        print(f"Files targeted for deletion: {stats['files_to_delete']}")
        print(f"Successful deletions: {stats['successful_deletions']}")
        print(f"Failed deletions: {stats['failed_deletions']}")
        print(f"Total size deleted: {stats['total_size_deleted_mb']} MB ({stats['total_size_deleted_gb']} GB)")
        print(f"Deletion log: {csv_output_path if csv_created else 'Failed to create'}")
        
        return stats


def main():
    # Validate configuration
    if not BUCKET_NAME:
        print("Error: AWS_S3_BUCKET_NAME environment variable is required.")
        print("Please set it in your .env file or environment.")
        return
    
    try:
        # Initialize cleaner
        cleaner = S3FileCleaner(bucket_name=BUCKET_NAME)
        
        # Show what will be cleaned
        print(f"S3 File Cleaner")
        print(f"Bucket: {BUCKET_NAME}")
        print(f"Folder: {S3_FOLDER_PATH}")
        print(f"Will delete files containing: {', '.join(DELETE_PATTERNS)}")
        
        # Start cleaning
        stats = cleaner.clean_files(
            s3_folder_path=S3_FOLDER_PATH,
            patterns=DELETE_PATTERNS,
            csv_output_path=CSV_OUTPUT_PATH
        )
        
        if 'cancelled' in stats:
            print("\nOperation was cancelled by user.")
        elif stats['successful_deletions'] > 0:
            print(f"\nCleaning completed! {stats['successful_deletions']} files deleted successfully.")
            if stats['failed_deletions'] > 0:
                print(f"Warning: {stats['failed_deletions']} files failed to delete.")
        else:
            print("\nNo files were deleted.")
            
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please provide credentials via:")
        print("1. Environment variables in .env file (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)")
        print("2. AWS credentials file (~/.aws/credentials)")
        print("3. IAM role (if running on EC2)")
        
    except KeyboardInterrupt:
        print("\nDeletion interrupted by user.")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main() 