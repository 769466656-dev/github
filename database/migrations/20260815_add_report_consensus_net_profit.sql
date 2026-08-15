-- 将历史上误名为 revenue_forecast 的同花顺预测净利润列改为准确名称。
-- 执行前请确认当前数据库为 wucai_trade。
ALTER TABLE trade_report_consensus
    CHANGE COLUMN revenue_forecast net_profit_forecast DECIMAL(20,2)
    COMMENT '预测净利润（接口原始单位）';

