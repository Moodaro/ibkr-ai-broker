"""Tests for audit backup system."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from packages.audit_backup import AuditBackupManager, BackupError


@pytest.fixture
def temp_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test_audit.db"
    
    # Create database with test data
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            data TEXT,
            timestamp DATETIME
        )
    """)
    cursor.execute(
        "INSERT INTO events (event_type, data, timestamp) VALUES (?, ?, ?)",
        ("test_event", "test data", datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    
    return db_path


@pytest.fixture
def backup_manager(tmp_path, temp_db):
    """Create backup manager with test database."""
    backup_dir = tmp_path / "backups"
    return AuditBackupManager(
        db_path=str(temp_db),
        backup_dir=str(backup_dir),
        retention_days=30,
    )


class TestAuditBackupManager:
    """Test audit backup manager."""
    
    def test_create_backup(self, backup_manager):
        """Test creating a backup."""
        backup_path = backup_manager.create_backup()
        
        assert backup_path.exists()
        assert backup_path.suffix == ".db"
        assert "audit_" in backup_path.name
        
        # Verify checksum file exists
        checksum_path = backup_path.with_suffix(".db.sha256")
        assert checksum_path.exists()
    
    def test_backup_contains_data(self, backup_manager):
        """Test backup contains database data."""
        backup_path = backup_manager.create_backup()
        
        # Open backup and verify data
        conn = sqlite3.connect(str(backup_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 1
    
    def test_verify_backup_valid(self, backup_manager):
        """Test verifying valid backup."""
        backup_path = backup_manager.create_backup()
        
        assert backup_manager.verify_backup(backup_path) is True
    
    def test_verify_backup_corrupted_checksum(self, backup_manager):
        """Test verifying backup with wrong checksum fails."""
        backup_path = backup_manager.create_backup()
        
        # Corrupt checksum file
        checksum_path = backup_path.with_suffix(".db.sha256")
        checksum_path.write_text("invalid_checksum")
        
        assert backup_manager.verify_backup(backup_path) is False
    
    def test_verify_backup_corrupted_file(self, backup_manager):
        """Test verifying corrupted backup fails."""
        backup_path = backup_manager.create_backup()
        
        # Corrupt backup file
        with open(backup_path, "ab") as f:
            f.write(b"corrupted data")
        
        assert backup_manager.verify_backup(backup_path) is False
    
    def test_verify_backup_missing(self, backup_manager):
        """Test verifying non-existent backup fails."""
        backup_path = Path("/nonexistent/backup.db")
        
        assert backup_manager.verify_backup(backup_path) is False
    
    def test_list_backups(self, backup_manager):
        """Test listing backups."""
        # Create multiple backups
        backup1 = backup_manager.create_backup(datetime.utcnow() - timedelta(hours=2))
        backup2 = backup_manager.create_backup(datetime.utcnow() - timedelta(hours=1))
        backup3 = backup_manager.create_backup(datetime.utcnow())
        
        backups = backup_manager.list_backups()
        
        assert len(backups) == 3
        # Should be sorted newest first
        assert backups[0] == backup3
        assert backups[1] == backup2
        assert backups[2] == backup1
    
    def test_cleanup_old_backups(self, backup_manager):
        """Test cleaning up old backups."""
        # Create old backup (40 days ago)
        old_time = datetime.utcnow() - timedelta(days=40)
        old_backup = backup_manager.create_backup(old_time)
        
        # Create recent backup
        recent_backup = backup_manager.create_backup()
        
        # Cleanup
        deleted_count = backup_manager.cleanup_old_backups()
        
        assert deleted_count == 1
        assert not old_backup.exists()
        assert recent_backup.exists()
    
    def test_restore_backup(self, backup_manager, tmp_path):
        """Test restoring from backup."""
        # Create backup
        backup_path = backup_manager.create_backup()
        
        # Create new target database
        target_path = tmp_path / "restored.db"
        
        # Restore
        backup_manager.restore_backup(backup_path, target_path)
        
        assert target_path.exists()
        
        # Verify restored data
        conn = sqlite3.connect(str(target_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == 1
    
    def test_restore_backup_invalid_fails(self, backup_manager, tmp_path):
        """Test restoring invalid backup fails."""
        backup_path = tmp_path / "invalid_backup.db"
        backup_path.write_text("not a valid database")
        
        target_path = tmp_path / "restored.db"
        
        with pytest.raises(BackupError):
            backup_manager.restore_backup(backup_path, target_path)
    
    def test_get_backup_info(self, backup_manager):
        """Test getting backup information."""
        backup_path = backup_manager.create_backup()
        
        info = backup_manager.get_backup_info(backup_path)
        
        assert info["exists"] is True
        assert info["size_bytes"] > 0
        assert info["timestamp"] is not None
        assert info["valid"] is True
    
    def test_get_backup_info_missing(self, backup_manager):
        """Test getting info for non-existent backup."""
        backup_path = Path("/nonexistent/backup.db")
        
        info = backup_manager.get_backup_info(backup_path)
        
        assert info["exists"] is False
        assert info["size_bytes"] == 0
        assert info["valid"] is False
    
    def test_create_backup_nonexistent_db_fails(self, tmp_path):
        """Test creating backup of non-existent database fails."""
        manager = AuditBackupManager(
            db_path=str(tmp_path / "nonexistent.db"),
            backup_dir=str(tmp_path / "backups"),
        )
        
        with pytest.raises(BackupError):
            manager.create_backup()
    
    def test_backup_directory_created(self, tmp_path, temp_db):
        """Test backup directory is created if missing."""
        backup_dir = tmp_path / "new_backup_dir"
        
        manager = AuditBackupManager(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
        )
        
        assert backup_dir.exists()
    
    def test_multiple_backups_same_day(self, backup_manager):
        """Test creating multiple backups on same day."""
        import time
        
        backup1 = backup_manager.create_backup()
        time.sleep(1.1)  # Ensure different timestamp
        backup2 = backup_manager.create_backup()
        
        assert backup1 != backup2
        assert backup1.exists()
        assert backup2.exists()
