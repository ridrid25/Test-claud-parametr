// Records Chroma Loop gameplay: 360x640 mobile viewport, 1080x1920 video.
// Board state is injected via localStorage so the level solves in exactly 5 taps.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const N = 1, E = 2, S = 4, W = 8;
function rotate(mask, times) {
  let m = mask & 15;
  for (let i = 0; i < ((times % 4) + 4) % 4; i++) {
    m = (m & N ? E : 0) | (m & E ? S : 0) | (m & S ? W : 0) | (m & W ? N : 0);
  }
  return m;
}
function dirTo(x, y, nx, ny) {
  if (nx === x && ny === y - 1) return N;
  if (nx === x + 1 && ny === y) return E;
  if (nx === x && ny === y + 1) return S;
  if (nx === x - 1 && ny === y) return W;
  throw new Error("not adjacent");
}

const COLS = 6, ROWS = 7;
// Hand-designed closed loop (clockwise), verified adjacent & unique.
const PATH = [
  [1,0],[2,0],[3,0],[4,0],[4,1],[5,1],[5,2],[5,3],[4,3],[4,4],[5,4],[5,5],
  [4,5],[4,6],[3,6],[2,6],[1,6],[1,5],[0,5],[0,4],[1,4],[1,3],[0,3],[0,2],
  [1,2],[1,1],
];
// Cells left mis-rotated; each needs exactly one tap. Tap order = natural sweep.
const MISROT = new Map([
  ["3,0", 1], // straight E|W shown perpendicular
  ["5,2", 1], // straight N|S shown perpendicular
  ["4,4", 3], // corner, one turn short
  ["1,6", 3],
  ["0,3", 3],
]);
const TAP_ORDER = [[3,0],[5,2],[4,4],[1,6],[0,3]];

function buildBoard() {
  const empty = () => ({ mask:0, solved:0, base:0, rot:0, kind:"normal", clicks:0, unlocked:true, coinBonus:false });
  const board = Array.from({length: ROWS}, () => Array.from({length: COLS}, empty));
  // sanity: unique + adjacency + closed
  const seen = new Set();
  for (let i = 0; i < PATH.length; i++) {
    const [x,y] = PATH[i];
    const key = `${x},${y}`;
    if (seen.has(key)) throw new Error("dup " + key);
    seen.add(key);
    const [px,py] = PATH[(i-1+PATH.length)%PATH.length];
    const [nx,ny] = PATH[(i+1)%PATH.length];
    const solved = dirTo(x,y,px,py) | dirTo(x,y,nx,ny);
    const rot = MISROT.get(key) ?? 0;
    const c = board[y][x];
    c.solved = solved; c.base = solved; c.rot = rot; c.mask = rotate(solved, rot);
  }
  return board;
}

function isSolved(board) {
  const h = board.length, w = board[0].length;
  const DX = {[N]:0,[E]:1,[S]:0,[W]:-1}, DY = {[N]:-1,[E]:0,[S]:1,[W]:0}, OPP = {[N]:S,[E]:W,[S]:N,[W]:E};
  for (let y=0;y<h;y++) for (let x=0;x<w;x++) {
    const mask = board[y][x].mask & 15;
    if (!mask) continue;
    for (const d of [N,E,S,W]) {
      if (!(mask & d)) continue;
      const nx = x+DX[d], ny = y+DY[d];
      if (nx<0||ny<0||nx>=w||ny>=h) return false;
      if (!(board[ny][nx].mask & OPP[d])) return false;
    }
  }
  return true;
}

(async () => {
  const board = buildBoard();
  if (isSolved(board)) throw new Error("board must start unsolved");
  // verify the tap plan solves it and no intermediate state solves early
  const sim = JSON.parse(JSON.stringify(board));
  for (let i = 0; i < TAP_ORDER.length; i++) {
    const [x,y] = TAP_ORDER[i];
    const c = sim[y][x];
    c.rot = (c.rot + 1) % 4;
    c.mask = rotate(c.base, c.rot);
    const solved = isSolved(sim);
    if (i < TAP_ORDER.length - 1 && solved) throw new Error("solved too early at tap " + (i+1));
    if (i === TAP_ORDER.length - 1 && !solved) throw new Error("not solved after final tap");
  }
  console.log("tap plan verified: 5 taps close the loop");

  const save = {
    coins: 1240, gems: 87, level: 40, skin: "neon", bg: "space", mascot: "default",
    ownedSkins: ["neon"], ownedBgs: ["clean","space"], ownedMascots: ["default"],
    music: false, sounds: false, lastTrack: -1, totalCoins: 5230, dailyDay: 3,
    lastClaim: null, freeHints: 3, chestsOpened: 4, hintsUsed: 2,
    maxLevelRewarded: 39, tutorial: { l1:true,l2:true,l3:true,shopHint:true,firstWin:true },
    loopCores: 1, ownedSplashEffects: ["default","cyan-pulse"], selectedSplashEffect: "cyan-pulse",
    level30MilestoneClaimed: true, levelBoardBonusClaimed: {}, pendingFreeChestLevel: null,
    effectsQuality: "full",
    rewardedAds: { day: "", views: 0, lastRewardAt: 0, receipts: [] },
  };
  const run = { level: 40, board, boardBonus: null };

  const outDir = path.join(__dirname, "video-out");
  fs.rmSync(outDir, { recursive: true, force: true });

  const browser = await chromium.launch({ headless: true, executablePath: "/opt/pw-browsers/chromium" });
  const context = await browser.newContext({
    viewport: { width: 360, height: 640 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    userAgent: "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    recordVideo: { dir: outDir, size: { width: 1080, height: 1920 } },
  });

  await context.addInitScript(([saveJson, runJson]) => {
    try {
      localStorage.setItem("chromaloop:v7", saveJson);
      localStorage.setItem("chromaloop:run:v1", runJson);
    } catch {}
    // Touch ripple indicator: 40px translucent white circle, 300ms.
    const attach = () => {
      const style = document.createElement("style");
      style.textContent = `
        .__tap-ripple{position:fixed;width:40px;height:40px;border-radius:50%;
          background:rgba(255,255,255,.55);pointer-events:none;z-index:99999;
          transform:translate(-50%,-50%) scale(.4);animation:__tapr .3s ease-out forwards;}
        @keyframes __tapr{0%{opacity:.9;transform:translate(-50%,-50%) scale(.4);}
          100%{opacity:0;transform:translate(-50%,-50%) scale(1.6);}}`;
      document.head.appendChild(style);
      window.addEventListener("pointerdown", (e) => {
        const d = document.createElement("div");
        d.className = "__tap-ripple";
        d.style.left = e.clientX + "px";
        d.style.top = e.clientY + "px";
        document.body.appendChild(d);
        setTimeout(() => d.remove(), 350);
      }, true);
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", attach);
    else attach();
  }, [JSON.stringify(save), JSON.stringify(run)]);

  const page = await context.newPage();
  const tCreated = Date.now();
  const marks = { pageCreated: 0 };

  await page.goto("https://chroma-loop-dream.lovable.app", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForSelector("text=TAP TO START", { timeout: 30000 });
  await page.waitForTimeout(1200);

  async function tapEl(locator) {
    const box = await locator.boundingBox();
    if (!box) throw new Error("no box");
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  }

  await tapEl(page.locator("button:has-text('TAP TO START')"));
  await page.waitForSelector(".play-mega", { timeout: 15000 });
  await page.waitForTimeout(900);
  await tapEl(page.locator(".play-mega"));
  await page.waitForSelector(".board button.cell", { timeout: 15000 });
  await page.waitForTimeout(1000);

  const cells = page.locator(".board > button.cell");
  const count = await cells.count();
  if (count !== COLS * ROWS) throw new Error(`expected ${COLS*ROWS} cells, got ${count}`);
  // Confirm the injected board is the one on screen (level pill says 40).
  const pill = await page.locator(".game-level-pill").innerText();
  console.log("level pill:", pill.replace(/\s+/g, " "));

  const tapTimes = [];
  for (const [x, y] of TAP_ORDER) {
    await tapEl(cells.nth(y * COLS + x));
    tapTimes.push(Date.now());
    await page.waitForTimeout(780);
  }
  // The 5th tap solves it; .board gains class "won" right away.
  await page.waitForSelector(".board.won", { timeout: 5000 });
  const tFlash = Date.now();
  await page.waitForTimeout(2500);

  await page.close();
  const video = page.video();
  const videoPath = await video.path();
  await context.close();
  await browser.close();

  const meta = {
    videoPath,
    tCreated,
    tapTimesRel: tapTimes.map((t) => (t - tCreated) / 1000),
    flashRel: (tFlash - tCreated) / 1000,
  };
  fs.writeFileSync(path.join(__dirname, "record-meta.json"), JSON.stringify(meta, null, 2));
  console.log(JSON.stringify(meta, null, 2));
})().catch((e) => { console.error(e); process.exit(1); });
