-- 智慧井场 - PostgreSQL 业务库初始化
-- 设备台账 / 告警 / 工单 / 知识源 / 反馈（阶段二/三用表先建前 3 张）

CREATE TABLE IF NOT EXISTS devices (
    id              BIGSERIAL PRIMARY KEY,
    site_id         VARCHAR(32)  NOT NULL,
    well_id         VARCHAR(32)  NOT NULL,
    device_id       VARCHAR(64)  NOT NULL UNIQUE,
    device_name     VARCHAR(128) NOT NULL,
    device_type     VARCHAR(32)  NOT NULL DEFAULT 'pumping_unit',
    manufacturer    VARCHAR(128),
    model           VARCHAR(128),
    install_date    DATE,
    rated_power_kw  NUMERIC(10,2),
    rated_freq      NUMERIC(10,2) DEFAULT 50.0,
    status          VARCHAR(16)  NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE devices IS '设备台账';

CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    alert_uid       VARCHAR(64)   NOT NULL UNIQUE,
    site_id         VARCHAR(32)   NOT NULL,
    well_id         VARCHAR(32),
    device_id       VARCHAR(64),
    fault_type      VARCHAR(64),
    level           VARCHAR(16)   NOT NULL DEFAULT 'info',  -- info / warning / critical
    title           VARCHAR(256)  NOT NULL,
    description     TEXT,
    confidence      NUMERIC(5,2),
    evidence        JSONB,
    recommendation  TEXT,
    status          VARCHAR(16)   NOT NULL DEFAULT 'pending', -- pending / acknowledged / resolved / closed
    source_agent    VARCHAR(64),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

COMMENT ON TABLE alerts IS '告警记录';

CREATE TABLE IF NOT EXISTS work_orders (
    id              BIGSERIAL PRIMARY KEY,
    order_uid       VARCHAR(64)   NOT NULL UNIQUE,
    alert_id        BIGINT REFERENCES alerts(id),
    site_id         VARCHAR(32)   NOT NULL,
    well_id         VARCHAR(32),
    device_id       VARCHAR(64),
    title           VARCHAR(256)  NOT NULL,
    description     TEXT,
    actions_taken   TEXT,
    actual_cause    TEXT,            -- 关闭时回填，供阶段三沉淀知识
    status          VARCHAR(16)   NOT NULL DEFAULT 'created', -- created/assigned/processing/resolved/closed
    priority        VARCHAR(16)   NOT NULL DEFAULT 'normal', -- low / normal / high / urgent
    assignee        VARCHAR(64),
    created_by      VARCHAR(64)   NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    assigned_at     TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

COMMENT ON TABLE work_orders IS '工单';

-- 知识源（阶段二用，预留）
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id              BIGSERIAL PRIMARY KEY,
    source_name     VARCHAR(256) NOT NULL,
    source_type     VARCHAR(32)  NOT NULL DEFAULT 'document', -- document / faq / manual
    file_path       VARCHAR(512),
    content_hash    VARCHAR(64),
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',  -- pending / indexed / failed
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE knowledge_sources IS '知识文档源（阶段二启用）';

-- 反馈（阶段三用，预留）
CREATE TABLE IF NOT EXISTS feedback (
    id              BIGSERIAL PRIMARY KEY,
    work_order_id   BIGINT REFERENCES work_orders(id),
    diagnosis_id    VARCHAR(64),
    feedback_type   VARCHAR(32)  NOT NULL DEFAULT 'correction', -- correction / confirmation / enhancement
    content         TEXT,
    submitted_by    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE feedback IS '人工反馈（阶段三自进化 RAG 用）';

-- 索引
CREATE INDEX IF NOT EXISTS idx_devices_site_well ON devices(site_id, well_id);
CREATE INDEX IF NOT EXISTS idx_alerts_site_level_status ON alerts(site_id, level, status);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_work_orders_site ON work_orders(site_id);
