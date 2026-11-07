import pymysql
from pymysql.cursors import DictCursor


class Database:
    def __init__(self, config):
        self.host = config["host"]
        self.port = int(config["port"])
        self.user = config["user"]
        self.password = config["password"]
        self.database = config["database"]
        self.conn = None
        self.cursor = None
        self.connect()

    def __del__(self):
        self.close()

    def connect(self):
        try:
            self.conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                autocommit=False,
                cursorclass=DictCursor,
            )
            self.cursor = self.conn.cursor()
        except pymysql.Error as e:
            raise Exception(f"Error connecting to database: {e}") from e

    def close(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn:
            self.conn.close()
            self.conn = None

    def execute(self, query, params=None):
        try:
            self.cursor.execute(query, params or ())
            self.conn.commit()
            return self.cursor.lastrowid
        except pymysql.Error as e:
            self.conn.rollback()
            raise Exception(f"Error executing query: {e}") from e

    def executemany(self, query, params_seq):
        try:
            self.cursor.executemany(query, params_seq)
            self.conn.commit()
        except pymysql.Error as e:
            self.conn.rollback()
            raise Exception(f"Error executing query: {e}") from e

    def fetchall(self, query=None, params=None):
        if query is not None:
            self.cursor.execute(query, params or ())
        return self.cursor.fetchall()

    def fetchone(self, query=None, params=None):
        if query is not None:
            self.cursor.execute(query, params or ())
        return self.cursor.fetchone()

    def init_schema(self):
        statements = [
            """
            CREATE TABLE IF NOT EXISTS constituents (
                ticker VARCHAR(16) PRIMARY KEY,
                name VARCHAR(64) NOT NULL DEFAULT '',
                weight DECIMAL(10, 4) NULL,
                source VARCHAR(16) NOT NULL DEFAULT '0050',
                updated_at DATETIME NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS price_history (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                ticker VARCHAR(16) NOT NULL,
                price DECIMAL(12, 4) NOT NULL,
                open DECIMAL(12, 4) NULL,
                pct_vs_open DECIMAL(10, 4) NULL,
                fetched_at DATETIME NOT NULL,
                INDEX idx_price_ticker_time (ticker, fetched_at)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                ticker VARCHAR(16) NOT NULL,
                side ENUM('buy', 'sell') NOT NULL,
                shares DECIMAL(16, 4) NOT NULL,
                price DECIMAL(12, 4) NOT NULL,
                trade_date DATE NOT NULL,
                note VARCHAR(255) NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_tx_ticker_date (ticker, trade_date)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS positions (
                ticker VARCHAR(16) PRIMARY KEY,
                shares DECIMAL(16, 4) NOT NULL,
                avg_cost DECIMAL(12, 4) NOT NULL,
                first_buy_date DATE NOT NULL,
                last_trade_date DATE NOT NULL,
                realized_pnl DECIMAL(16, 4) NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                ticker VARCHAR(16) NOT NULL,
                rule_type ENUM('pct_vs_open', 'price_above', 'price_below') NOT NULL,
                threshold DECIMAL(12, 4) NOT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                last_triggered_at DATETIME NULL
            )
            """,
        ]
        for sql in statements:
            self.execute(sql)
