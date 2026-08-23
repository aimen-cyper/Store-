from pathlib import Path

ROOT=Path(__file__).parents[1]
API=ROOT/'apps/api/dhat_store'


def read(path): return (API/path).read_text(encoding='utf-8')


def test_composed_entrypoint_mounts_management_and_payments():
    text=read('app.py')
    assert 'management_router' in text
    assert 'payment_router' in text
    assert 'include_router' in text


def test_fine_grained_permission_matrix_exists():
    text=read('dependencies.py')
    for code in ['users.read','users.suspend','orders.manage','wallet.adjust','payments.manage','providers.manage','services.manage','pricing.manage','coupons.manage','support.manage','analytics.read','audit.read','admins.manage','settings.manage']:
        assert code in text


def test_payment_webhook_is_verified_and_idempotent():
    text=read('payment_routes.py')
    assert 'compare_digest' in text
    assert 'external_id' in text
    assert 'idempotent' in text


def test_mvp_hardening_migration_is_explicit():
    text=(ROOT/'alembic/versions/0003_mvp_hardening.py').read_text(encoding='utf-8')
    assert 'op.add_column' in text
    assert 'op.create_index' in text
    assert 'op.bulk_insert' in text


def test_no_application_create_all_in_migrations():
    for path in (ROOT/'alembic/versions').glob('*.py'):
        text=path.read_text(encoding='utf-8')
        assert 'metadata.create_all' not in text
        assert '.create_all(' not in text
