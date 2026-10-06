// Music cue sheet for the editor (FILM_BRIEF.md §4), timed from src/timeline.ts.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { AFTERNOON, COLD, DURATION, END, MORNING, NEXT, NIGHT, SEG } from "../src/timeline";

const ts = (s: number) => {
  const whole = Math.round(s * 10) / 10;
  const m = Math.floor(whole / 60);
  const sec = whole - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
};
const rows: Array<[string, string, string]> = [
  [`${ts(SEG.cold[0])}–${ts(SEG.cold[1])}`, "无音乐", `只有杂音和碎片。锁定 88.7 在 ${ts(COLD.lock[0])}，提示音之后留 0.5 秒安静；${ts(COLD.dawn[0])} 起画面由黑转亮`],
  [`${ts(SEG.morning[0])}–${ts(SEG.morning[1])}`, "明亮温暖的 City Pop 或 Funk 纯音乐，约 100–110 BPM", `播放页在 ${ts(MORNING.open[0])}–${ts(MORNING.open[1])} 打开，此处音量稍微抬高；${ts(AFTERNOON.light[0])} 起转入下午`],
  [`${ts(SEG.afternoon[0])}–${ts(SEG.afternoon[1])}`, "Lo-fi 或爵士化的 Hip-hop 节拍，约 85–90 BPM", `幕后拆解 ${ts(AFTERNOON.breakdown[0])}–${ts(AFTERNOON.collapse[1])} 音量压低，${ts(AFTERNOON.player)} 进入播放页后恢复`],
  [`${ts(SEG.night[0])}–${ts(SEG.night[1])}`, "独奏爵士钢琴慢板", `主持字幕 ${ts(NIGHT.host[0])}–${ts(NIGHT.host[1])} 压低约 10dB，与混音面板同步（${ts(NIGHT.host[0] - 0.1)} 开始下压，${ts(NIGHT.host[1] + 0.6)} 回到原音量）；雨声音效 ${ts(NIGHT.rainIn[0])}–${ts(NIGHT.rainOut[1])}`],
  [`${ts(SEG.nextMorning[0])}–${ts(DURATION)}`, "钢琴主题的再现，封面墙段逐渐推高，在 Logo 出现时收尾", `封面墙 ${ts(NEXT.wall[0])}–${ts(NEXT.wall[1])}；Logo ${ts(END.icon)}；最后 1 秒（${ts(END.fade[0])}–${ts(END.fade[1])}）淡出`],
];
const md = `# WaveCast 概念宣传片：音乐时间表

由 \`apps/video/scripts/build-cues.ts\` 按 \`src/timeline.ts\` 生成，与渲染结果同一套时间。片长 ${ts(DURATION)}（${DURATION} 秒，30fps）。

| 时间 | 建议的音乐 | 说明 |
|---|---|---|
${rows.map((r) => `| ${r.join(" | ")} |`).join("\n")}
`;
const out = join(__dirname, "../out");
mkdirSync(out, { recursive: true });
writeFileSync(join(out, "music-cues.md"), md);
writeFileSync(join(__dirname, "../music-cues.md"), md);
console.log(md);
