from pathlib import Path

def test_required_tree_exists():
    for p in ['apps/api/dhat_store/main.py','apps/api/dhat_store/models.py','alembic/versions/0001_initial.py','apps/web/src/main.tsx','apps/admin/src/main.tsx']:
        assert Path(p).exists(), p

def test_no_plaintext_env():
    assert not Path('.env').exists()

def test_migration_is_explicit():
    text=Path('alembic/versions/0001_initial.py').read_text()
    assert 'op.create_table' in text and 'create_all' not in text
