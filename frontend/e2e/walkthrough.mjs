// End-to-end walkthrough against a running offline-demo server.
//   BASE=http://localhost:8765 INVITE=letmein OUT=/tmp/shots node e2e/walkthrough.mjs
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:8765";
const OUT = process.env.OUT ?? "e2e-shots";
const INVITE = process.env.INVITE ?? "";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
const step = (s) => console.log("•", s);

step("register");
await page.goto(BASE);
await shot("01-login");
await page.getByRole("tab", { name: "Create account" }).click();
await page.getByLabel("Full name").fill("Test Researcher");
await page.getByLabel("Email").fill(`e2e${Date.now()}@example.com`);
await page.getByLabel(/Password/).fill("password123");
if (INVITE) await page.getByLabel("Invite code").fill(INVITE);
await page.getByRole("button", { name: "Create account" }).last().click();
await page.getByRole("heading", { name: "Start a research session" }).waitFor();
await shot("02-home");

step("new session + analysis stream");
await page.getByRole("button", { name: "New research session" }).first().click();
await page.getByLabel("What are you researching?").fill("Large language models for clinical decision support");
await page.getByRole("button", { name: "Create and find papers" }).click();
await page.getByText("Analysis complete").waitFor({ timeout: 60_000 });
await page.waitForTimeout(500);
await shot("03-papers");
await page.getByPlaceholder(/Filter by title/).fill("model");
await page.getByRole("button", { name: "Read abstract" }).first().click();

step("themes");
await page.getByRole("link", { name: /^Themes/ }).click();
await page.locator("article").first().waitFor();
await shot("04-themes");

step("gaps: add own gap with check");
await page.getByRole("link", { name: /^Gaps/ }).click();
await page.getByRole("button", { name: "Add your own gap" }).click();
await page.getByLabel("Gap in one line").fill("No evaluation of LLM triage tools in rural hospitals");
await page.getByRole("button", { name: "Add gap" }).click();
await page.getByText(/Novelty check/).waitFor({ timeout: 30_000 });
await page.getByLabel("Your notes").fill("Talk to the regional health board.");
await page.getByText("Saved").first().waitFor({ timeout: 5_000 });
await page.getByRole("button", { name: "How could I design a study to address this?" }).click();
await page.getByText(/Sources \(/).first().waitFor({ timeout: 30_000 });
await shot("05-gap-detail");
// pin an AI gap
await page.locator("aside[aria-label=Gaps] a").last().click();
await page.getByRole("button", { name: "Pin" }).click();
await page.getByRole("button", { name: "Unpin" }).waitFor();

step("ask");
await page.getByRole("link", { name: "Ask" }).click();
await page.getByLabel("Your question").fill("What are the main findings?");
await page.keyboard.press("Enter");
await page.getByText(/Sources \(/).first().waitFor({ timeout: 30_000 });
await shot("06-ask");

step("write");
await page.getByRole("link", { name: "Write" }).click();
await page.getByRole("button", { name: "Suggest an outline" }).click();
await page.getByText("What to cover in this section").waitFor({ timeout: 60_000 });
const text = "Large language models have been evaluated for diagnosis support in several settings [1]. "
  + "Accuracy is generally reported as high on benchmark questions. Some studies find lower performance in real clinical notes [2]. "
  + "Few studies evaluate patient outcomes directly.";
await page.locator("textarea[id^=text-]").fill(text);
await page.getByText("Saved").first().waitFor({ timeout: 6_000 });
await page.getByRole("button", { name: "Save and check" }).click();
await page.getByText("Feedback on your draft").waitFor({ timeout: 30_000 });
await shot("07-write");
await page.getByRole("button", { name: /Example draft/ }).click();
await page.getByRole("button", { name: "Generate example" }).click();
await page.locator("h4").first().waitFor({ timeout: 60_000 });
const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Word" }).click()]);
console.log("  downloaded", dl.suggestedFilename());
// reload keeps the text
await page.reload();
await page.locator("textarea[id^=text-]").waitFor();
const kept = await page.locator("textarea[id^=text-]").inputValue();
if (!kept.startsWith("Large language models")) throw new Error("text not persisted");

step("share");
await page.getByRole("link", { name: "Share" }).last().click();
await page.getByRole("heading", { name: "People with access" }).waitFor();
await shot("08-share");

step("mobile");
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("link", { name: /^Gaps/ }).click();
await page.waitForTimeout(400);
await shot("09-mobile-gaps");

step("logout");
await page.setViewportSize({ width: 1440, height: 1000 });
await page.getByRole("button", { name: "Log out" }).click();
await page.getByRole("heading", { name: "Welcome back" }).waitFor();

await browser.close();
// 401s are the expected "not logged in" check on /me.
const real = errors.filter((e) => !/favicon|status of 401/.test(e));
if (real.length) { console.log("Console errors:\n" + real.join("\n")); process.exit(1); }
console.log("All steps passed, no console errors.");
