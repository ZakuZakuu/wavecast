# UI 辅助小字清单（只记录，未决定去留）

2026-10-18。来源为发布版本 `485ea1252c070d090b57cf6bc3e1cc7814ca3d2f`。用户将与 Claude 讨论，本轮未删改任何文案，也未决定保留/删除/改写/只显示一次。

范围：与用户点名的弹窗底部说明相似的常驻说明、空态、条件状态和短反馈。动态值用方括号表示，原有换行在表中合并。没有穷举全部错误消息、无障碍标签、按钮名和节目本身的正文。

| 编号 | 位置 | 当前文案 | 出现条件 | 代码定位 |
| --- | --- | --- | --- | --- |
| P01 | 主持词弹窗底部 | 正在说的那句会高亮，说过的话可以随时翻回来看。 | 弹窗打开时常驻；未按是否已有稿件区分 | [player/narration-sheet.tsx:78](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/narration-sheet.tsx#L78) |
| P02 | 节目路线底部 | 后面的章节会在你听的时候准备好，曲目可能会微调。 | 路线弹窗常驻；当前未按节目是否已完整生成区分 | [player/route-sheet.tsx:86](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/route-sheet.tsx#L86) |
| P03 | 主持词空态 | 主持还没开口。开口之后，说过的话会留在这里。 | 尚无已发布主持词时 | [player/narration-sheet.tsx:75](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/narration-sheet.tsx#L75) |
| P04 | 播放状态条 | 正在准备接下来的内容，马上就好 | 状态条处于 preparing 时 | [player/now-line.tsx:58](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/now-line.tsx#L58) |
| P05 | 播放状态条次行 | 已准备到 [时间] | preparing 状态；时间为动态值 | [player/now-line.tsx:59](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/now-line.tsx#L59) |
| P06 | 进度条上方 | 这部分还在准备 | 拖动或键盘跳转超过已发布边界时短暂显示 | [player/progress-bar.tsx:18](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/progress-bar.tsx#L18) |
| P07 | 更多菜单·导出 | 完整节目准备好后可以导出 | 节目尚未 MATERIALIZED 时 | [player/more-sheet.tsx:72](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/more-sheet.tsx#L72) |
| P08 | 更多菜单·停止准备 | 已经准备好的部分会保留 | 显示停止后台准备/停止播放操作时 | [player/more-sheet.tsx:80](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/more-sheet.tsx#L80) |
| P09 | 下一首操作反馈 | 下一首还在准备 | 目标歌曲起点尚不可跳转时 toast | [player/player-screen.tsx:168](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/player-screen.tsx#L168) |
| P10 | 游客少放这类反馈 | 已记下。登录后，这些偏好会一直保存 | 未登录用户点击少放这类时 toast | [player/player-screen.tsx:195](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/player/player-screen.tsx#L195) |
| T01 | 开播等待页底部 | 音乐几秒内就会响起来，后面的内容边播边准备。 | 开播等待页常驻；原文在两句之间换行 | [tune/tuning-in.tsx:132](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/tune/tuning-in.tsx#L132) |
| T02 | 调谐器说明 | 松手会自动对准最近的台 | 位于两个电台之间时；锁定后此处改为电台描述 | [tune/tune-page.tsx:280](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/tune/tune-page.tsx#L280) |
| T03 | 调频输入占位 | 说一个歌手、一首歌，或者你在做什么 | 输入为空时 placeholder | [tune/tune-page.tsx:327](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/tune/tune-page.tsx#L327) |
| H01 | 首页节目预览底部 | 点播放之后，才会开始准备这档节目。 | 首页节目预览弹窗 | [home/programme-sheet.tsx:61](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/home/programme-sheet.tsx#L61) |
| H02 | 首页推荐辅助行 | 登录后，这里会换成按你口味准备的节目 | 游客首页；旁有登录入口 | [home/home-page.tsx:262](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/home/home-page.tsx#L262) |
| H03 | 首页推荐空态 | 还没有可以推荐的节目。 | 推荐列表为空时；旁有去调一档入口 | [home/home-page.tsx:274](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/home/home-page.tsx#L274) |
| D01 | 节目详情路线下方 | 从 [艺人]《[歌名]》开始。后面的曲目会边听边排，可能会微调。 | 有路线时；方括号为动态内容占位 | [programme/programme-detail-page.tsx:297](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/programme-detail-page.tsx#L297) |
| D02 | 节目详情播放按钮附近 | 点播放之后，才会开始准备这档节目。 | 详情默认 note；会被其他播放状态文案替换 | [programme/programme-detail-page.tsx:180](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/programme-detail-page.tsx#L180) |
| D03 | 节目详情状态 | 这档节目正在播放。 | 该档节目正在播放时 | [programme/programme-detail-page.tsx:183](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/programme-detail-page.tsx#L183) |
| D04 | 节目详情续听说明 | 上次听到 [时间]，全长约 [分钟] 分钟。 | 已听过但当前未播；方括号为动态值 | [programme/programme-detail-page.tsx:189](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/programme-detail-page.tsx#L189) |
| D05 | 节目详情准备状态 | 音乐几秒内就会响起来，后面的内容边播边准备。 | 详情 phase=preparing 时 | [programme/programme-detail-page.tsx:191](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/programme-detail-page.tsx#L191) |
| S01 | 分享弹窗底部 | 对方打开链接后，点播放才会生成属于他的一份节目，内容不一定和你听到的完全一样。 | 分享弹窗常规说明 | [programme/share-sheet.tsx:88](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/share-sheet.tsx#L88) |
| S02 | 分享复制失败说明 | 这台设备没让我们复制，可以长按上面的地址自己复制。 | 复制失败时，替换上一条 | [programme/share-sheet.tsx:87](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/programme/share-sheet.tsx#L87) |
| L01 | 节目库·最近空态 | 听过的节目会留在这里，下次从上次的位置接着听。 | 最近页签无条目时 | [library/library-page.tsx:229](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/library/library-page.tsx#L229) |
| L02 | 节目库·保存空态 | 在播放页的“更多”里保存完整节目，它会留在这里。 | 保存页签无条目时；后续快捷入口方案可能涉及此句 | [library/library-page.tsx:231](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/library/library-page.tsx#L231) |
| L03 | 节目库·创建空态 | 在调频页开播的节目会留在这里。 | 创建页签无条目时 | [library/library-page.tsx:232](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/library/library-page.tsx#L232) |
| A01 | 少放歌手弹窗说明 | 推荐和调频会少放他们。取消后，之后的推荐就不再回避。 | 少放歌手列表上方常驻 | [account/avoid-artists-sheet.tsx:48](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/account/avoid-artists-sheet.tsx#L48) |
| A02 | 少放歌手空态 | 还没有。播放时点“少放这类”，那首歌的歌手会出现在这里。 | 少放歌手列表为空时 | [account/avoid-artists-sheet.tsx:61](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/account/avoid-artists-sheet.tsx#L61) |
| A03 | 邮箱登录底部 | 无需密码，首次登录会自动创建账号。 | 尚未发送验证码时 | [account/email-login.tsx:150](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/account/email-login.tsx#L150) |
| A04 | 验证码底部 | 5 分钟内有效，没收到可以看看垃圾邮件。 | 已经发送验证码时；与上一条同一位置 | [account/email-login.tsx:150](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/account/email-login.tsx#L150) |
| B01 | 浏览器建议条 | 推荐使用 iPhone Safari 体验，桌面端建议使用 Chrome 或 Edge。 | 桌面浏览器建议条，可关闭 | [browser-guidance.tsx:78](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/browser-guidance.tsx#L78) |
| B02 | 微信浏览器引导底部 | 没有这个选项？复制链接，再粘贴到浏览器。网页无法代你切换浏览器。 | 微信内打开的引导弹窗 | [browser-guidance.tsx:110](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/browser-guidance.tsx#L110) |
| B03 | 浏览器引导复制反馈 | 打开浏览器，粘贴链接就能继续。 | 复制成功时 | [browser-guidance.tsx:113](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/browser-guidance.tsx#L113) |
| B04 | 浏览器引导复制失败反馈 | 自动复制不可用，请手动复制。 | 自动复制失败时 | [browser-guidance.tsx:113](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/browser-guidance.tsx#L113) |
| B05 | 桌面侧卡底部 | 推荐用 iPhone Safari 体验，桌面端建议用 Chrome 或 Edge。扫码后若在微信中打开，请从右上角菜单切换到浏览器。 | 宽屏桌面二维码侧卡 | [desktop-stage.tsx:61](https://github.com/ZakuZakuu/wavecast/blob/485ea1252c070d090b57cf6bc3e1cc7814ca3d2f/apps/web/components/desktop-stage.tsx#L61) |

## 其他动态说明

- mini player 的次行是电台信息或“暂停在 [时间]”，属于实时状态；见 `components/mini-player.tsx`。
- 当请求的艺人没有可播音源时，路线会显示“暂时没有找到 [艺人] 可以播放的音源，已为你搭配相近的曲目。”，由 `lib/source-notice.ts` 拼接。
- 更多菜单中的“正在准备完整节目…”等操作状态、节目详情的额度/错误反馈会随实际结果变化。后续讨论可结合正常、等待、完成、失败四种页面状态一起查看；本清单不替代这些状态逻辑。

用户明确：**本轮不替其决定哪些小字有必要。** 后续逐项讨论即可，避免将本表当成删除任务单。
