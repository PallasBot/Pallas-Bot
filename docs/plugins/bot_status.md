# Bot_Status

## 邮箱通知配置

要想使用指令首先需要配置好在 [.env](/.env#L3) 中配置好 SUPERUSERS。

离线邮箱通知会向 BotConfig 中设置好的 admin 与 [.env](/.env#L128) 中设置的邮箱发送邮件，因此想给号主发邮件，请给牛牛配置好 admins。

没有给 Bot 配置 admins 的请使用 [config.mongodb](/tools/config/config.mongodb) 来为牛牛添加她的号主账号。

邮箱配置请参考各邮箱的 smtp 配置。

配置好邮箱后发送 `测试邮件` 可以测试邮箱配置是否成功。
