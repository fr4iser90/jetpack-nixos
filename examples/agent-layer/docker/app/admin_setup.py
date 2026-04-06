"""
Admin User Setup & Claim System
Erster Start Admin Claim Prozess
"""
from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timedelta

from . import db
from .auth import create_user, hash_password

logger = logging.getLogger(__name__)


ADMIN_CLAIM_OTP_ENV = "AGENT_ADMIN_CLAIM_OTP"


def generate_admin_claim_otp() -> str:
    """
    Generiere einmaligen OTP für ersten Admin Claim
    Wird beim ersten Start in Log und optional in ENV ausgegeben
    """
    otp = secrets.token_urlsafe(24)

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            # Lösche alte Claim OTPs
            cur.execute("DELETE FROM admin_claim_otp")

            # Speichere neuen OTP gültig für 24h
            cur.execute("""
                INSERT INTO admin_claim_otp (otp_hash, expires_at)
                VALUES (%s, %s)
            """, (
                hash_password(otp),
                datetime.utcnow() + timedelta(hours=24)
            ))
            conn.commit()

    # Gib OTP im Terminal Log aus
    logger.info("")
    logger.info("=" * 80)
    logger.info("  🎯 ERSTER START ADMIN CLAIM")
    logger.info("")
    logger.info(f"  Admin Claim OTP: {otp}")
    logger.info("")
    logger.info("  Besuche /control/claim um den ersten Admin User zu erstellen")
    logger.info("  Dieser OTP ist 24 Stunden gültig")
    logger.info("=" * 80)
    logger.info("")

    # Optional: Setze als Env Variable für Docker Logs
    os.environ[ADMIN_CLAIM_OTP_ENV] = otp

    return otp


def claim_admin_user(email: str, password: str, otp: str) -> bool:
    """
    Claim ersten Admin User mit OTP
    """
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT otp_hash, expires_at
                FROM admin_claim_otp
                WHERE used_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()

            if not row:
                return False

            otp_hash, expires_at = row

            # Prüfe OTP Gültigkeit
            from .auth import verify_password
            if not verify_password(otp, otp_hash):
                return False

            if datetime.utcnow() > expires_at:
                return False

            # Erstelle Admin User
            user = create_user(email, password, role="admin")

            # Markiere OTP als benutzt
            cur.execute("""
                UPDATE admin_claim_otp
                SET used_at = NOW(), claimed_by_user_id = %s
                WHERE otp_hash = %s
            """, (user.id, otp_hash))
            conn.commit()

    logger.info("✅ Admin User erfolgreich erstellt: %s", email)
    return True


def is_first_start() -> bool:
    """
    Prüfe ob es der erste Start ist und kein Admin User existiert
    """
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            admin_count = cur.fetchone()[0]
            return admin_count == 0


def setup_admin_claim_if_needed() -> None:
    """
    Wenn noch kein Admin existiert generiere Claim OTP
    Wird automatisch bei Startup aufgerufen
    """
    if is_first_start():
        generate_admin_claim_otp()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Benutzung: python -m app.admin_setup <email> <passwort>")
        print("Erstellt oder aktualisiert Admin User direkt über Kommandozeile")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    
    db.init_pool()

    from .auth import get_user_by_email, update_user_password
    
    existing = get_user_by_email(email)
    
    if existing:
        update_user_password(existing.id, password)
        print(f"ℹ️  Admin User existiert bereits: {email}")
        print(f"ℹ️  Passwort wurde aktualisiert")
    else:
        user = create_user(email, password, role="admin")
        print(f"✅ Admin User erfolgreich erstellt: {email}")

    print(f"✅ Du kannst dich jetzt anmelden unter /control/")
