-- 技术底座数据库结构（SQLite）
-- 对齐《系统管理+流程引擎需求规格说明书》第 3 章

-- ============ 系统管理（RBAC + ABAC，对应 M5） ============

CREATE TABLE IF NOT EXISTS sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    real_name VARCHAR(50),
    email VARCHAR(100),
    phone VARCHAR(20),
    actor_type VARCHAR(20) DEFAULT 'HUMAN',
    department_id INTEGER,
    status TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_role (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    parent_id INTEGER DEFAULT 0,
    description VARCHAR(255),
    status TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_permission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    target_type VARCHAR(20) NOT NULL,
    target_ref VARCHAR(100) NOT NULL,
    data_scope VARCHAR(20) DEFAULT 'ALL',
    abac_condition VARCHAR(255),
    status TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_resource (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER DEFAULT 0,
    name VARCHAR(50) NOT NULL,
    code VARCHAR(100) UNIQUE NOT NULL,
    permission_code VARCHAR(100),
    type VARCHAR(20) NOT NULL,
    path VARCHAR(200),
    component VARCHAR(200),
    icon VARCHAR(50),
    http_method VARCHAR(10),
    sort_order INTEGER DEFAULT 0,
    status TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_user_role (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS sys_role_permission (
    role_id INTEGER NOT NULL,
    permission_id INTEGER NOT NULL,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS sys_role_resource (
    role_id INTEGER NOT NULL,
    resource_id INTEGER NOT NULL,
    PRIMARY KEY (role_id, resource_id)
);

-- ============ 流程引擎（对应 M6） ============

CREATE TABLE IF NOT EXISTS flow_definition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    flow_type VARCHAR(20) NOT NULL,
    trigger_type VARCHAR(20) DEFAULT 'MANUAL',
    trigger_behavior VARCHAR(100),
    description VARCHAR(255),
    node_graph TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    status TINYINT DEFAULT 0,
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS flow_instance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    def_id INTEGER NOT NULL,
    business_key VARCHAR(50) NOT NULL,
    business_object_refs TEXT,
    current_activity_ids TEXT,
    variables TEXT,
    creator_id INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'RUNNING',
    priority INTEGER DEFAULT 0,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS flow_task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    activity_id VARCHAR(50) NOT NULL,
    activity_type VARCHAR(20) NOT NULL,
    activity_name VARCHAR(100),
    role_ref VARCHAR(50),
    behavior_ref VARCHAR(100),
    sub_flow_ref VARCHAR(100),
    assignee_id INTEGER,
    assignee_name VARCHAR(50),
    status VARCHAR(20) DEFAULT 'TODO',
    action VARCHAR(20),
    comment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    claimed_at DATETIME,
    done_at DATETIME,
    deadline DATETIME
);

CREATE TABLE IF NOT EXISTS flow_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL,
    activity_id VARCHAR(50),
    activity_name VARCHAR(100),
    operator_id INTEGER,
    operator_name VARCHAR(50),
    action VARCHAR(20),
    comment TEXT,
    from_activity VARCHAR(50),
    to_activity VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 审计日志 ============

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username VARCHAR(50),
    action VARCHAR(100),
    detail TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 业务表（批次 1：基础数据，字段口径见 yaml/m1-object-model.yaml 与 docs/批次1-实现契约.md） ============

CREATE TABLE IF NOT EXISTS patient (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no VARCHAR(20) NOT NULL UNIQUE,
    patient_name VARCHAR(50) NOT NULL,
    gender VARCHAR(20) NOT NULL,
    birth_date DATE,
    age INTEGER,
    id_type VARCHAR(20),
    id_no VARCHAR(50),
    phone VARCHAR(30) NOT NULL,
    address VARCHAR(200),
    occupation VARCHAR(50),
    allergy_history VARCHAR(500),
    patient_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    remark VARCHAR(500),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

-- INV-01：同一「证件类型 + 证件号码」不得重复建档（仅约束未删除且已填证件号的记录）
CREATE UNIQUE INDEX IF NOT EXISTS ux_patient_id_doc ON patient (id_type, id_no) WHERE id_no IS NOT NULL AND id_no <> '' AND flag = 1;

CREATE TABLE IF NOT EXISTS syndrome_type (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    syndrome_code VARCHAR(20) NOT NULL UNIQUE,
    syndrome_name VARCHAR(50) NOT NULL UNIQUE,
    diagnosis_method VARCHAR(30) NOT NULL,
    syndrome_description VARCHAR(500),
    common_symptoms VARCHAR(500),
    corresponding_treatment VARCHAR(200),
    syndrome_status VARCHAR(20) NOT NULL DEFAULT 'ENABLED',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS formula_template (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_code VARCHAR(20) NOT NULL UNIQUE,
    formula_name VARCHAR(100) NOT NULL UNIQUE,
    formula_type VARCHAR(30) NOT NULL,
    source VARCHAR(100),
    "function" VARCHAR(200),
    indication VARCHAR(500),
    default_doses INTEGER,
    formula_status VARCHAR(20) NOT NULL DEFAULT 'ENABLED',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS formula_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_template_id INTEGER NOT NULL,
    item_id VARCHAR(50) NOT NULL,
    seq_no INTEGER NOT NULL,
    herb_id INTEGER NOT NULL,
    common_dose NUMERIC NOT NULL,
    decoction_method VARCHAR(30),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_formula_item_master ON formula_item (formula_template_id, flag);

CREATE TABLE IF NOT EXISTS herb (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    herb_code VARCHAR(20) NOT NULL UNIQUE,
    herb_name VARCHAR(50) NOT NULL UNIQUE,
    alias_name VARCHAR(100),
    herb_category VARCHAR(30),
    nature_meridian VARCHAR(200),
    efficacy VARCHAR(300),
    min_common_dose NUMERIC NOT NULL,
    max_common_dose NUMERIC NOT NULL,
    toxicity_level VARCHAR(20) NOT NULL DEFAULT 'NONE',
    toxic_dose_limit NUMERIC,
    special_managed TINYINT NOT NULL DEFAULT 0,
    stock_quantity NUMERIC NOT NULL DEFAULT 0,
    low_stock_threshold NUMERIC,
    origin VARCHAR(100),
    spec VARCHAR(50),
    herb_status VARCHAR(20) NOT NULL DEFAULT 'ENABLED',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE TABLE IF NOT EXISTS herb_stock_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    herb_id INTEGER NOT NULL,
    flow_no VARCHAR(30) NOT NULL UNIQUE,
    biz_type VARCHAR(30) NOT NULL,
    quantity NUMERIC NOT NULL,
    biz_date DATETIME NOT NULL,
    operator_id VARCHAR(50) NOT NULL,
    prescription_id INTEGER,
    inbound_no VARCHAR(50),
    remark VARCHAR(300),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_herb_stock_flow_herb ON herb_stock_flow (herb_id, flag);

-- ============ 业务表（批次 2：门诊业务流，字段口径见 yaml/m1-object-model.yaml 与 docs/批次2-实现契约.md） ============

CREATE TABLE IF NOT EXISTS visit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_no VARCHAR(20) NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    visit_type VARCHAR(20) NOT NULL,
    previous_visit_id INTEGER,
    register_time DATETIME NOT NULL,
    receive_time DATETIME,
    doctor_id VARCHAR(50) NOT NULL,
    dept_code VARCHAR(30) NOT NULL,
    chief_complaint VARCHAR(500),  -- v1.5：挂号时可为空，接诊环节录入并必填
    present_illness VARCHAR(1000),
    past_history VARCHAR(1000),
    vital_signs VARCHAR(200),
    visit_status VARCHAR(20) NOT NULL DEFAULT 'REGISTERED',
    remark VARCHAR(500),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_visit_patient ON visit (patient_id, flag);
CREATE INDEX IF NOT EXISTS ix_visit_status ON visit (visit_status, flag);

-- 从表：Visit.FourDiagnosis（基数 ZERO_OR_ONE → 每就诊至多一份，唯一索引保证）
CREATE TABLE IF NOT EXISTS four_diagnosis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL,
    four_diagnosis_id VARCHAR(50) NOT NULL,
    inquiry_cold_heat VARCHAR(500),
    inquiry_sweat VARCHAR(500),
    inquiry_head_body VARCHAR(500),
    inquiry_diet VARCHAR(500),
    inquiry_sleep VARCHAR(500),
    inquiry_excretion VARCHAR(500),
    inquiry_emotion VARCHAR(500),
    inspection_face VARCHAR(200),
    inspection_shape VARCHAR(200),
    tongue_body VARCHAR(30),
    tongue_coating VARCHAR(30),
    auscultation_voice VARCHAR(200),
    auscultation_smell VARCHAR(200),
    pulse_code VARCHAR(30) NOT NULL,
    pulse_detail VARCHAR(200),
    four_diagnosis_summary VARCHAR(500),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_four_diagnosis_visit ON four_diagnosis (visit_id) WHERE flag = 1;

CREATE TABLE IF NOT EXISTS syndrome_diagnosis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_no VARCHAR(20) NOT NULL UNIQUE,
    visit_id INTEGER NOT NULL,
    diagnosis_method VARCHAR(30) NOT NULL,
    syndrome_id INTEGER NOT NULL,
    syndrome_nature VARCHAR(20) NOT NULL,
    diagnosis_basis VARCHAR(500) NOT NULL,
    treatment_principle VARCHAR(200) NOT NULL,
    conclusion_status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_diagnosis_visit ON syndrome_diagnosis (visit_id, flag);
-- INV-02：同一就诊下「主证」唯一
CREATE UNIQUE INDEX IF NOT EXISTS ux_diagnosis_primary ON syndrome_diagnosis (visit_id) WHERE syndrome_nature = 'PRIMARY' AND flag = 1;

CREATE TABLE IF NOT EXISTS prescription (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_no VARCHAR(20) NOT NULL UNIQUE,
    visit_id INTEGER NOT NULL,
    patient_id INTEGER NOT NULL,
    doctor_id VARCHAR(50) NOT NULL,
    prescription_type VARCHAR(30) NOT NULL,
    formula_template_id INTEGER,
    doses INTEGER NOT NULL,
    usage_method VARCHAR(30) NOT NULL,
    decoction_instruction VARCHAR(300),
    medical_advice VARCHAR(500),
    prescribe_time DATETIME NOT NULL,
    submit_time DATETIME,
    prescription_status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    reviewer_id VARCHAR(50),
    review_time DATETIME,
    reject_reason VARCHAR(500),
    cancel_reason VARCHAR(500),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_prescription_visit ON prescription (visit_id, flag);
CREATE INDEX IF NOT EXISTS ix_prescription_status ON prescription (prescription_status, flag);

CREATE TABLE IF NOT EXISTS prescription_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id INTEGER NOT NULL,
    item_id VARCHAR(50) NOT NULL,
    seq_no INTEGER NOT NULL,
    herb_id INTEGER NOT NULL,
    single_dose NUMERIC NOT NULL,
    decoction_method VARCHAR(30),
    remark VARCHAR(200),
    over_dose_reason VARCHAR(300),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_prescription_item_master ON prescription_item (prescription_id, flag);

CREATE TABLE IF NOT EXISTS dispense_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispense_no VARCHAR(20) NOT NULL UNIQUE,
    prescription_id INTEGER NOT NULL,
    dispenser_id VARCHAR(50) NOT NULL,
    checker_id VARCHAR(50),
    dispense_time DATETIME NOT NULL,
    issue_time DATETIME,
    record_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    remark VARCHAR(300),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

-- 一张处方对应一条调剂发药记录（一对一）
CREATE UNIQUE INDEX IF NOT EXISTS ux_dispense_prescription ON dispense_record (prescription_id) WHERE flag = 1;

CREATE TABLE IF NOT EXISTS follow_up (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    follow_up_no VARCHAR(20) NOT NULL UNIQUE,
    patient_id INTEGER NOT NULL,
    source_visit_id INTEGER NOT NULL,
    actual_visit_id INTEGER,
    planned_follow_up_date DATE NOT NULL,
    actual_follow_up_date DATE,
    efficacy_level VARCHAR(20),
    symptom_change VARCHAR(500),
    continue_medication TINYINT,
    record_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    remark VARCHAR(500),
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    flag TINYINT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_followup_patient ON follow_up (patient_id, flag);
CREATE INDEX IF NOT EXISTS ix_followup_status ON follow_up (record_status, flag);
