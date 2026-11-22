const { readFile, writeFile } = await import("node:fs/promises");
const { url, output, result } = JSON.parse(await readFile(__REQUEST__, "utf8"));
const task = await taskSpace("KuKuTool 视频下载");
try {
  const page = task.page("p1");
  await page.goto("https://dy.kukutool.com/en");
  await page.fill('input[placeholder="Paste text with link"]', url);
  await page.click("text=Parse Video", { label: "Parse source video link" });
  let button;
  try {
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some((item) =>
      item.innerText.trim() === "DownloadVideo" && item.getClientRects().length > 0 && !item.disabled
    ), undefined, { timeout: 28_000 });
    const snapshot = await page.snapshot({ scope: "full_page" });
    button = /button[^\n]*\[ref=(\d+)[^\n]*\]\n\s+text "DownloadVideo"/.exec(snapshot)?.[1];
    if (!button) throw new Error("no button");
  } catch {
    throw new Error("KuKuTool 未返回下载结果。请确认链接有效，若网站要求验证，可手动下载后使用本地文件入口。");
  }
  try {
    const downloading = page.waitForEvent("download", { timeout: 45_000 });
    const [download] = await Promise.all([
      downloading, page.click("@" + button, { label: "Download source video" }),
    ]);
    await download.saveAs(output);
    await writeFile(result, JSON.stringify({ title: download.suggestedFilename() }));
  } catch {
    throw new Error("KuKuTool 已解析链接，但没能下载视频。可重试或手动下载后导入。");
  }
} catch (error) {
  await writeFile(result, JSON.stringify({ error: error.message }));
} finally {
  await task.finish({ keep: [] });
}
