from alembic import op
import sqlalchemy as sa

revision='0003_mvp_hardening'
down_revision='0002_production_subsystems'
branch_labels=None
depends_on=None

PERMISSIONS=['users.read','users.update','users.suspend','orders.read','orders.manage','orders.refund','wallet.read','wallet.adjust','payments.read','payments.manage','providers.read','providers.manage','services.read','services.manage','pricing.read','pricing.manage','coupons.read','coupons.manage','support.read','support.manage','analytics.read','audit.read','admins.manage','settings.read','settings.manage']
ROLES=['OWNER','ADMIN','FINANCE','SUPPORT','MODERATOR','CUSTOMER']


def upgrade():
    op.add_column('deposit_requests',sa.Column('proof_url',sa.String(500),nullable=True))
    op.create_index('ix_deposits_user_status','deposit_requests',['user_id','status'])
    op.create_index('ix_audit_action_created','audit_logs',['action','created_at'])
    op.create_index('ix_external_orders_outcome','external_orders',['outcome','last_checked_at'])
    op.bulk_insert(sa.table('permissions',sa.column('id',sa.Integer()),sa.column('code',sa.String())),[{'id':i+1,'code':p} for i,p in enumerate(PERMISSIONS)])
    op.bulk_insert(sa.table('roles',sa.column('id',sa.Integer()),sa.column('name',sa.String())),[{'id':i+1,'name':r} for i,r in enumerate(ROLES)])
    op.bulk_insert(sa.table('role_permissions',sa.column('role_id',sa.Integer()),sa.column('permission_id',sa.Integer())),[{'role_id':1,'permission_id':i+1} for i in range(len(PERMISSIONS))]+[{'role_id':2,'permission_id':i+1} for i in range(len(PERMISSIONS)) if PERMISSIONS[i] not in {'admins.manage'}}])


def downgrade():
    op.drop_index('ix_external_orders_outcome',table_name='external_orders')
    op.drop_index('ix_audit_action_created',table_name='audit_logs')
    op.drop_index('ix_deposits_user_status',table_name='deposit_requests')
    op.drop_column('deposit_requests','proof_url')
