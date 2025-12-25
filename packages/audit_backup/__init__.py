"""Audit Database Backup System.

This module provides automated backup of the audit database with:
- Scheduled backups (daily by default)
- 30-day rotation (automatic cleanup)
- Backup verification (integrity check)
- Restore procedure

Usage:
    from packages.audit_backup import AuditBackupManager
    
    manager = AuditBackupManager(
        db_path="data/audit.db",
        backup_dir="backups",
        retention_days=30
    )
    
    # Create backup
    backup_path = manager.create_backup()
    
    # Verify backup
    if manager.verify_backup(backup_path):
        print("Backup valid")
    
    # Cleanup old backups
    manager.cleanup_old_backups()
    
    # Restore from backup
    manager.restore_backup(backup_path)
"""

import hashlib
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

__all__ = ["AuditBackupManager", "BackupError"]


class BackupError(Exception):
    """Raised when backup operation fails."""
    pass


class AuditBackupManager:
    """Manage audit database backups with rotation and verification."""
    
    def __init__(
        self,
        db_path: str = "data/audit.db",
        backup_dir: str = "backups",
        retention_days: int = 30,
    ):
        """Initialize backup manager.
        
        Args:
            db_path: Path to audit database
            backup_dir: Directory for backups
            retention_days: Days to retain backups before deletion
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days
        
        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    def create_backup(self, timestamp: Optional[datetime] = None) -> Path:
        """Create database backup with timestamp.
        
        Args:
            timestamp: Backup timestamp (defaults to now)
            
        Returns:
            Path to backup file
            
        Raises:
            BackupError: If backup creation fails
        """
        if not self.db_path.exists():
            raise BackupError(f"Database not found: {self.db_path}")
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Generate backup filename with timestamp
        backup_name = f"audit_{timestamp.strftime('%Y%m%d_%H%M%S')}.db"
        backup_path = self.backup_dir / backup_name
        
        try:
            # Use SQLite backup API for consistent snapshot
            source_conn = sqlite3.connect(str(self.db_path))
            backup_conn = sqlite3.connect(str(backup_path))
            
            with backup_conn:
                source_conn.backup(backup_conn)
            
            source_conn.close()
            backup_conn.close()
            
            # Create checksum file
            checksum = self._calculate_checksum(backup_path)
            checksum_path = backup_path.with_suffix(".db.sha256")
            checksum_path.write_text(checksum)
            
            return backup_path
        
        except Exception as e:
            # Cleanup partial backup
            if backup_path.exists():
                backup_path.unlink()
            raise BackupError(f"Backup failed: {e}")
    
    def verify_backup(self, backup_path: Path) -> bool:
        """Verify backup integrity using checksum.
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            True if backup is valid, False otherwise
        """
        if not backup_path.exists():
            return False
        
        checksum_path = backup_path.with_suffix(".db.sha256")
        if not checksum_path.exists():
            return False
        
        try:
            # Read stored checksum
            stored_checksum = checksum_path.read_text().strip()
            
            # Calculate current checksum
            current_checksum = self._calculate_checksum(backup_path)
            
            # Compare
            if stored_checksum != current_checksum:
                return False
            
            # Try to open database to verify it's not corrupted
            conn = sqlite3.connect(str(backup_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            
            return result[0] == "ok"
        
        except Exception:
            return False
    
    def list_backups(self) -> list[Path]:
        """List all backup files sorted by timestamp (newest first).
        
        Returns:
            List of backup file paths
        """
        backups = sorted(
            self.backup_dir.glob("audit_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return backups
    
    def cleanup_old_backups(self) -> int:
        """Delete backups older than retention period.
        
        Returns:
            Number of backups deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted_count = 0
        
        for backup_path in self.list_backups():
            # Parse timestamp from filename
            try:
                timestamp_str = backup_path.stem.replace("audit_", "")
                backup_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if backup_time < cutoff_date:
                    # Delete backup and checksum
                    backup_path.unlink()
                    checksum_path = backup_path.with_suffix(".db.sha256")
                    if checksum_path.exists():
                        checksum_path.unlink()
                    deleted_count += 1
            
            except Exception:
                # Skip files with invalid names
                continue
        
        return deleted_count
    
    def restore_backup(self, backup_path: Path, target_path: Optional[Path] = None) -> None:
        """Restore database from backup.
        
        Args:
            backup_path: Path to backup file
            target_path: Target path for restore (defaults to original db_path)
            
        Raises:
            BackupError: If restore fails or backup is invalid
        """
        if not self.verify_backup(backup_path):
            raise BackupError(f"Backup verification failed: {backup_path}")
        
        if target_path is None:
            target_path = self.db_path
        
        try:
            # Create backup of current database before restore
            if target_path.exists():
                current_backup = target_path.with_suffix(".db.pre-restore")
                shutil.copy2(target_path, current_backup)
            
            # Restore from backup
            shutil.copy2(backup_path, target_path)
        
        except Exception as e:
            raise BackupError(f"Restore failed: {e}")
    
    def get_backup_info(self, backup_path: Path) -> dict:
        """Get information about a backup file.
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            Dictionary with backup info (size, timestamp, valid)
        """
        info = {
            "path": str(backup_path),
            "exists": backup_path.exists(),
            "size_bytes": 0,
            "timestamp": None,
            "valid": False,
        }
        
        if not backup_path.exists():
            return info
        
        # Get file size
        info["size_bytes"] = backup_path.stat().st_size
        
        # Parse timestamp from filename
        try:
            timestamp_str = backup_path.stem.replace("audit_", "")
            backup_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            info["timestamp"] = backup_time.isoformat()
        except Exception:
            pass
        
        # Verify backup
        info["valid"] = self.verify_backup(backup_path)
        
        return info
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Hexadecimal checksum string
        """
        sha256_hash = hashlib.sha256()
        
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()
