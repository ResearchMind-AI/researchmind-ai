// Two people working on one session, in two separate browser sessions.
//   BASE=http://localhost:8765 INVITE=letmein OUT=/tmp/shots node e2e/collab.mjs
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:8765";
const OUT = process.env.OUT ?? "e2e-shots";
const INVITE = process.env.INVITE ?? "";
mkdirSync(OUT, { recursive: true });
const stamp = Date.now();
const browser = await chromium.launch();
const errors = [];
const step = (s) => console.log("•", s);

async function person(name, email) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && !/status of 40[13]/.test(m.text()) && errors.push(`${name}: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`${name}: ${e}`));
  await page.goto(BASE);
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/Password/).fill("password123");
  if (INVITE) await page.getByLabel("Invite code").fill(INVITE);
  await page.getByRole("button", { name: "Create account" }).last().click();
  await page.getByRole("heading", { name: "Start a research session" }).waitFor();
  return page;
}
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png` });

let vicky, priya;
const onFail = async (e) => {
  console.log(String(e).split("\n")[0]);
  try { await vicky?.screenshot({ path: `${OUT}/fail-vicky.png` }); await priya?.screenshot({ path: `${OUT}/fail-priya.png` }); } catch {}
  process.exit(1);
};
process.on("unhandledRejection", onFail);
process.on("uncaughtException", onFail);
step("two accounts");
vicky = await person("Vicky Srinivasan", `vicky${stamp}@example.com`);
priya = await person("Priya Raman", `priya${stamp}@example.com`);

step("Vicky starts a session and shares it with Priya");
await vicky.getByRole("button", { name: "New research session" }).first().click();
await vicky.getByLabel("What are you researching?").fill("Large language models for clinical decision support");
await vicky.getByRole("button", { name: "Create and find papers" }).click();
await vicky.getByText("Analysis complete").waitFor({ timeout: 60_000 });
await vicky.getByRole("link", { name: "Share" }).first().click();
await vicky.getByLabel("Email").fill(`priya${stamp}@example.com`);
await vicky.getByText("Contributor").click();
await vicky.getByRole("button", { name: "Share session" }).click();
await vicky.getByText(/Shared with priya/).waitFor();

step("Vicky writes the introduction (it becomes her section)");
await vicky.getByRole("link", { name: /^Write/ }).click();
await vicky.getByRole("button", { name: "Suggest an outline" }).click();
await vicky.getByText("What to cover in this section").waitFor({ timeout: 60_000 });
const saved = vicky.waitForResponse((r) => r.url().includes("/writing/sections/") && r.request().method() === "PUT" && r.ok());
await vicky.locator("textarea[id^=text-]").fill("Early evaluations report high accuracy on benchmark questions [1]. Real clinical notes are harder [2].");
await saved;

step("Priya proposes removing a paper, with a reason");
await priya.reload();
await priya.getByRole("link", { name: /Large language models/ }).first().click();
await priya.getByText("Working with Vicky").or(priya.getByText(/Vicky is here/)).first().waitFor();
await priya.getByRole("button", { name: "Propose removal" }).first().click();
await priya.getByText("Wrong study type").click();
await priya.getByLabel(/Add a note/).fill("It's a protocol, no results yet.");
await priya.getByRole("button", { name: "Propose removal" }).last().click();
await priya.getByText(/Proposed\. Vicky needs to approve it/).waitFor();
await priya.getByText(/You proposed removing paper 1/).waitFor();

step("Priya suggests an edit to Vicky's introduction and comments on a paper");
await priya.getByRole("link", { name: /^Write/ }).click();
await priya.getByText(/This section is .*Vicky Srinivasan's/).waitFor();
await priya.getByRole("button", { name: "Suggest an edit" }).click();
await priya.locator("textarea[id^=text-]").fill("Early evaluations report accuracy between 74% and 86% on benchmark questions [1]. Real clinical notes are harder [2].");
await priya.getByPlaceholder(/Why\?/).fill("Give the numbers");
await priya.getByRole("button", { name: "Send suggestion" }).click();
await priya.getByText(/Your suggested edit is waiting for Vicky/).waitFor();
await priya.getByRole("link", { name: /^Papers/ }).click();
await priya.getByRole("button", { name: /^Comments/ }).nth(1).click();
await priya.getByLabel("Comment", { exact: true }).fill("@Vicky the sample was only 3 psychiatrists. Worth flagging as a limitation?");
await priya.getByRole("button", { name: "Comment", exact: true }).click();
await priya.getByText(/only 3 psychiatrists/).waitFor();
await priya.keyboard.press("Escape");

step("Vicky sees what's new: the proposal, the suggestion and the mention");
await vicky.reload();
await vicky.getByText(/Priya is here/).waitFor({ timeout: 40_000 });
await vicky.getByRole("button", { name: /What's new/ }).click();
const news = vicky.getByRole("complementary", { name: "What's new" });
await news.getByText(/proposed removing paper 1/).first().waitFor();
await news.getByText(/suggested an edit in your section/).first().waitFor();
await news.getByText(/mentioned you/).waitFor();
await shot(vicky, "c1-whats-new");
await news.getByRole("button", { name: "Close what's new" }).click();

step("Vicky approves the removal");
await vicky.getByRole("link", { name: /^Papers/ }).click();
await vicky.getByText(/1 to review/).first().waitFor();
await vicky.getByText(/1 proposal needs your decision/).waitFor();
await shot(vicky, "c2-proposal");
await vicky.getByRole("button", { name: "Approve" }).click();
await vicky.getByText("Approved").waitFor();
await vicky.getByRole("tab", { name: /Removed/ }).click();
await vicky.getByText(/Removed · Wrong study type/).waitFor();

step("Vicky accepts Priya's suggested edit");
await vicky.getByRole("link", { name: /^Write/ }).click();
await vicky.getByText(/Priya Raman suggested an edit/).waitFor();
await shot(vicky, "c3-suggestion");
await vicky.getByRole("button", { name: "Accept" }).click();
await vicky.getByText("Edit accepted").waitFor();
const t = await vicky.locator("textarea[id^=text-]").inputValue();
if (!t.includes("74% and 86%")) throw new Error("accepted edit not applied");

step("history shows who did what");
await vicky.getByRole("button", { name: "History" }).first().click();
await vicky.getByText(/accepted Priya Raman's edit/).waitFor();
await vicky.keyboard.press("Escape");

step("Priya sees her edit was accepted; her own section is hers");
await priya.reload();
await priya.getByRole("link", { name: /^Write/ }).click();
await priya.getByText(/74% and 86%/).first().waitFor();
await browser.close();
if (errors.length) { console.log("Console errors:\n" + errors.join("\n")); process.exit(1); }
console.log("All collaboration steps passed, no console errors.");
