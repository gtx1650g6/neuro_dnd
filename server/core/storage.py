import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from server.core import config
from server.core.models import CampaignJournal, CampaignMeta, UserProfile, UserSettings


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_code TEXT PRIMARY KEY,
                id TEXT NOT NULL,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                avatar_url TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_code TEXT PRIMARY KEY,
                theme TEXT NOT NULL,
                language TEXT NOT NULL,
                FOREIGN KEY(user_code) REFERENCES users(user_code) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rooms (
                room_code TEXT PRIMARY KEY,
                host_user_code TEXT NOT NULL,
                name TEXT,
                is_public INTEGER NOT NULL,
                players_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                host_user_code TEXT NOT NULL,
                name TEXT NOT NULL,
                tone TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                players_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                journal_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                host_user_code TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        conn.commit()


# --- User Management ---
def user_exists(user_code: str) -> bool:
    try:
        uuid.UUID(user_code)
    except ValueError:
        return False

    with closing(_get_conn()) as conn:
        row = conn.execute("SELECT 1 FROM users WHERE user_code = ?", (user_code,)).fetchone()
        return row is not None


def get_user_profile(user_code: str) -> Optional[Dict[str, Any]]:
    with closing(_get_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_code = ?", (user_code,)).fetchone()
        return dict(row) if row else None


def save_user_profile(profile_data: Dict[str, Any]) -> None:
    with closing(_get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO users (user_code, id, username, email, hashed_password, avatar_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_code) DO UPDATE SET
                username=excluded.username,
                email=excluded.email,
                hashed_password=excluded.hashed_password,
                avatar_url=excluded.avatar_url
            """,
            (
                profile_data["user_code"],
                str(profile_data["id"]),
                profile_data["username"],
                profile_data["email"],
                profile_data["hashed_password"],
                profile_data.get("avatar_url"),
                str(profile_data["created_at"]),
            ),
        )
        conn.commit()


def find_user_by_email(email: str) -> Optional[UserProfile]:
    with closing(_get_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return UserProfile(**dict(row)) if row else None


def add_user_to_index(user_profile: UserProfile):
    # Backward-compatible no-op: JSON index is replaced with DB constraints/indexes.
    return None


# --- User settings ---
def get_user_settings(user_code: str) -> UserSettings:
    with closing(_get_conn()) as conn:
        row = conn.execute("SELECT theme, language FROM user_settings WHERE user_code = ?", (user_code,)).fetchone()
        if not row:
            return UserSettings()
        return UserSettings(**dict(row))


def save_user_settings(user_code: str, settings: UserSettings) -> None:
    with closing(_get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_code, theme, language)
            VALUES (?, ?, ?)
            ON CONFLICT(user_code) DO UPDATE SET
                theme=excluded.theme,
                language=excluded.language
            """,
            (user_code, settings.theme, settings.language),
        )
        conn.commit()


# --- Room Management ---
def get_all_rooms() -> List[Dict]:
    with closing(_get_conn()) as conn:
        rows = conn.execute("SELECT * FROM rooms").fetchall()

    rooms: List[Dict] = []
    for row in rows:
        room = dict(row)
        room["is_public"] = bool(room["is_public"])
        room["players"] = json.loads(room["players_json"])
        room.pop("players_json", None)
        rooms.append(room)
    return rooms


def write_all_rooms(rooms: List[Dict]):
    with closing(_get_conn()) as conn:
        conn.execute("DELETE FROM rooms")
        for room in rooms:
            conn.execute(
                """
                INSERT INTO rooms (room_code, host_user_code, name, is_public, players_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    room["room_code"],
                    room["host_user_code"],
                    room.get("name"),
                    1 if room.get("is_public") else 0,
                    json.dumps(room.get("players", []), ensure_ascii=False),
                    str(room.get("created_at", datetime.utcnow().isoformat())),
                ),
            )
        conn.commit()


# --- Campaigns ---
def create_campaign(meta: CampaignMeta, journal: CampaignJournal) -> None:
    with closing(_get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO campaigns (id, host_user_code, name, tone, difficulty, players_json, status, created_at, journal_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(meta.id),
                meta.host_user_code,
                meta.name,
                meta.tone,
                meta.difficulty,
                json.dumps(meta.players, ensure_ascii=False),
                meta.status,
                str(meta.created_at),
                journal.json(),
            ),
        )
        conn.commit()


def list_campaigns(user_code: str) -> List[CampaignMeta]:
    with closing(_get_conn()) as conn:
        rows = conn.execute("SELECT * FROM campaigns WHERE host_user_code = ? ORDER BY created_at DESC", (user_code,)).fetchall()

    result: List[CampaignMeta] = []
    for row in rows:
        data = dict(row)
        data["players"] = json.loads(data.pop("players_json"))
        data.pop("journal_json", None)
        result.append(CampaignMeta(**data))
    return result


def get_campaign(user_code: str, campaign_id: str) -> Optional[Tuple[CampaignMeta, CampaignJournal]]:
    with closing(_get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE host_user_code = ? AND id = ?",
            (user_code, campaign_id),
        ).fetchone()

    if not row:
        return None

    data = dict(row)
    journal = CampaignJournal.parse_raw(data.pop("journal_json"))
    data["players"] = json.loads(data.pop("players_json"))
    meta = CampaignMeta(**data)
    return meta, journal


def append_campaign_journal_entry(user_code: str, campaign_id: str, message_data: Dict[str, Any]) -> Optional[CampaignJournal]:
    campaign = get_campaign(user_code, campaign_id)
    if not campaign:
        return None

    meta, journal = campaign
    journal.entries.append(message_data)

    with closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE campaigns SET journal_json = ? WHERE id = ? AND host_user_code = ?",
            (journal.json(), campaign_id, user_code),
        )
        conn.commit()

    return journal


def save_campaign_checkpoint(user_code: str, campaign_id: str, payload: Dict[str, Any]) -> str:
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    with closing(_get_conn()) as conn:
        conn.execute(
            "INSERT INTO checkpoints (campaign_id, host_user_code, timestamp, payload_json) VALUES (?, ?, ?, ?)",
            (campaign_id, user_code, timestamp, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        conn.commit()
    return timestamp


def delete_campaign(user_code: str, campaign_id: str) -> bool:
    with closing(_get_conn()) as conn:
        cur = conn.execute("DELETE FROM campaigns WHERE host_user_code = ? AND id = ?", (user_code, campaign_id))
        conn.commit()
        return cur.rowcount > 0


# Keep backward compatibility for modules still importing these helpers.
def get_user_profile_file(user_code: str) -> Optional[Path]:
    return config.USERS_DIR / f"user_{user_code}" / "profile.json"


def get_user_settings_file(user_code: str) -> Optional[Path]:
    return config.USERS_DIR / f"user_{user_code}" / "settings.json"


def get_campaigns_dir(user_code: str) -> Optional[Path]:
    return config.USERS_DIR / f"user_{user_code}" / "campaigns"


def get_campaign_meta_file(user_code: str, campaign_id: str) -> Optional[Path]:
    return config.USERS_DIR / f"user_{user_code}" / "campaigns" / f"camp_{campaign_id}" / "meta.json"


def get_campaign_journal_file(user_code: str, campaign_id: str) -> Optional[Path]:
    return config.USERS_DIR / f"user_{user_code}" / "campaigns" / f"camp_{campaign_id}" / "journal.json"


def read_json(file_path: Path) -> Optional[Any]:
    # Legacy fallback for any remaining file-based reads.
    if not file_path.exists():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(file_path: Path, data: Any):
    # Legacy fallback for any remaining file-based writes.
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


init_db()
