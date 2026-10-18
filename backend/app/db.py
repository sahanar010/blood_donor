from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Enable PostGIS, create tables, bootstrap the admin user (dev convenience;
    use Alembic migrations for a production deployment)."""
    from app import models  # noqa: F401  (register tables)
    from app.enums import Role
    from app.security import hash_password

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)

    if settings.admin_email and settings.admin_password:
        with SessionLocal() as db:
            exists = db.scalar(select(models.User).where(models.User.email == settings.admin_email.lower()))
            if not exists:
                db.add(models.User(email=settings.admin_email.lower(),
                                   password_hash=hash_password(settings.admin_password),
                                   role=Role.ADMIN))
                db.commit()
