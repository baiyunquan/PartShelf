import sqlite3

from app.services.numeric_alias_index import ensure_numeric_aliases


def test_existing_dirty_row_does_not_break_remote_cache_upsert():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE jlc_components(lcsc INTEGER PRIMARY KEY,mfr TEXT,description TEXT,attributes TEXT)")
        conn.execute("INSERT INTO jlc_components VALUES(1,'RES','10k resistor','{}')")
        conn.commit()
        ensure_numeric_aliases(conn, "jlcparts")
        # Simulate an installation containing the original trigger and current parser metadata.
        conn.execute("DROP TRIGGER numeric_search_update")
        conn.execute("CREATE TRIGGER numeric_search_update AFTER UPDATE ON jlc_components BEGIN "
                     "INSERT OR IGNORE INTO numeric_search_dirty VALUES(NEW.lcsc); END")
        conn.execute("DELETE FROM numeric_search_meta WHERE key='trigger_version'")
        conn.commit()
        aliases = list(conn.execute("SELECT * FROM numeric_search_aliases"))
        report = ensure_numeric_aliases(conn, "jlcparts")
        assert not report["rebuilt"]
        assert list(conn.execute("SELECT * FROM numeric_search_aliases")) == aliases
        conn.execute("INSERT INTO numeric_search_dirty VALUES(1)")
        conn.execute("INSERT INTO jlc_components VALUES(1,'RES','20k resistor','{}') "
                     "ON CONFLICT(lcsc) DO UPDATE SET description=excluded.description")
        conn.commit()
        assert ensure_numeric_aliases(conn, "jlcparts")["scanned"] == 1
