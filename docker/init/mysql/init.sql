-- 智慧井场 - MySQL 模拟事件总线表
-- 本地开发环境：通过消息表 + 轮询机制模拟发布订阅

CREATE DATABASE IF NOT EXISTS wellsite_bus
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE wellsite_bus;

-- 事件消息表
CREATE TABLE IF NOT EXISTS event_messages (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    topic       VARCHAR(255) NOT NULL,
    payload     JSON NOT NULL,
    headers     JSON,
    status      VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending / delivered / dead
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    created_at  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    delivered_at TIMESTAMP(3) NULL,
    consumer_id VARCHAR(64) NULL,
    INDEX idx_status_created (status, created_at),
    INDEX idx_topic_status (topic(128), status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 订阅者表（记录哪些消费者订阅了哪些 topic 模式）
CREATE TABLE IF NOT EXISTS event_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    topic_pattern VARCHAR(255) NOT NULL,
    consumer_id VARCHAR(64) NOT NULL,
    consumer_url VARCHAR(512),
    created_at  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_consumer_topic (consumer_id, topic_pattern(128)),
    INDEX idx_topic_pattern (topic_pattern(128))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 死信表
CREATE TABLE IF NOT EXISTS event_dead_letters (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    original_id BIGINT NOT NULL,
    topic       VARCHAR(255) NOT NULL,
    payload     JSON NOT NULL,
    headers     JSON,
    error       TEXT,
    retry_count INT NOT NULL,
    created_at  TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_topic (topic(128)),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 授权 wellsite 用户
GRANT ALL PRIVILEGES ON wellsite_bus.* TO 'wellsite'@'%';
FLUSH PRIVILEGES;
