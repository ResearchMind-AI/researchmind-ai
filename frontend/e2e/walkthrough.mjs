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
step("triage: remove with reason, undo-able, key paper, note, restore");
await page.getByRole("button", { name: "Remove" }).first().click();
await page.getByText(/Paper 1 removed/).waitFor();
await page.getByRole("button", { name: "Off-topic" }).click();
await page.getByRole("button", { name: "Key paper" }).first().click();
await page.getByRole("button", { name: "Key paper", pressed: true }).first().waitFor();
await page.getByRole("button", { name: "+ Add a note" }).first().click();
await page.getByLabel(/Note on paper/).fill("Use in the introduction.");
await page.getByRole("button", { name: "Save note" }).click();
await page.getByText("Use in the introduction.").waitFor();
await page.getByRole("tab", { name: /Removed/ }).click();
await page.getByText("Removed · Off-topic").waitFor();
await shot("03b-removed");
await page.getByRole("button", { name: "Restore" }).click();
await page.getByText(/Nothing removed/).waitFor();
await page.getByRole("tab", { name: /^Kept/ }).click();
await page.getByRole("button", { name: "Remove" }).nth(2).click();
await page.getByText(/removed\./).waitFor();
await page.getByPlaceholder(/Filter by title/).fill("model");
await page.getByRole("button", { name: "Read abstract" }).first().click();
await page.getByPlaceholder(/Filter by title/).fill("");
step("add by DOI");
await page.getByRole("button", { name: "Add by DOI" }).click();
await page.getByLabel("DOI or doi.org link").fill("10.1234/e2e.1");
await page.getByRole("button", { name: "Add paper" }).click();
await page.getByText(/Added as paper/).waitFor();
await shot("03c-triage");
step("full text: badges with pages, try again");
await page.getByText(/Full text · 4 pages/).first().waitFor();
await page.getByText(/Full text for \d+ of \d+/).waitFor();
await page.getByRole("button", { name: /Try again|Get full texts/ }).click();
await page.getByText(/No more free copies found|Got the full text of/).waitFor({ timeout: 30_000 });

step("themes");
await page.getByRole("link", { name: /^Explore/ }).click();
await page.locator("article").first().waitFor();
await page.getByText(/group your kept papers/).waitFor();
await shot("04-themes");

step("gaps: add own gap with check");
await page.getByRole("link", { name: /^Gaps/ }).click();
await page.getByRole("button", { name: "Add your own gap" }).click();
await page.getByLabel("Gap in one line").fill("No evaluation of LLM triage tools in rural hospitals");
await page.getByRole("button", { name: "Add gap" }).click();
await page.getByText(/Novelty check/).waitFor({ timeout: 30_000 });
await page.getByLabel("Your notes").fill("Talk to the regional health board.");
await page.getByText("Saved").first().waitFor({ timeout: 5_000 });
step("research partner about the gap: notice, answer, add to notes");
await page.getByRole("button", { name: "Discuss with your research partner" }).click();
const partner = page.getByRole("complementary", { name: "Research partner" });
await partner.getByText("Your gap: No evaluation of LLM triage tools").waitFor();
await partner.getByRole("button", { name: "How could I design a study to address this?" }).click();
await partner.getByText(/Sources \(/).first().waitFor({ timeout: 30_000 });
await partner.getByRole("button", { name: "Add to my gap notes" }).first().click();
await page.getByText("Added to your gap notes").waitFor();
await shot("05-gap-detail");
// track an AI gap: it gets checked automatically
await page.locator("aside[aria-label=Gaps] a").last().click();
await page.getByRole("button", { name: "Track this gap" }).click();
await page.getByRole("button", { name: "Tracked" }).waitFor();
await page.getByText(/Novelty check:/).waitFor({ timeout: 30_000 });

step("research partner about the whole session");
await partner.getByRole("button", { name: "Ask about the whole session instead" }).click();
await partner.getByText("The whole session").waitFor();
await partner.getByLabel("Your question").fill("What are the main findings?");
await page.keyboard.press("Enter");
await partner.getByText(/Sources \(/).first().waitFor({ timeout: 30_000 });
await shot("06-ask");
await partner.getByRole("button", { name: "Close research partner" }).click();

step("write");
await page.getByRole("link", { name: /^Write/ }).click();
await page.getByRole("button", { name: "Suggest an outline" }).click();
await page.getByText("What to cover in this section").waitFor({ timeout: 60_000 });
const text = "Large language models have been evaluated for diagnosis support in several settings [1]. "
  + "Accuracy is generally reported as high on benchmark questions. Some studies find lower performance in real clinical notes [2]. "
  + "Few studies evaluate patient outcomes directly.";
const saved = page.waitForResponse((r) => r.url().includes("/writing/sections/") && r.request().method() === "PUT" && r.ok());
await page.locator("textarea[id^=text-]").fill(text);
await saved;
await page.getByRole("button", { name: "Save and check" }).click();
await page.getByText("Feedback on your draft").waitFor({ timeout: 30_000 });
await shot("07-write");
await page.getByRole("button", { name: /Example draft/ }).click();
await page.getByRole("button", { name: "Generate example" }).click();
await page.locator("h4").first().waitFor({ timeout: 60_000 });
const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Word", exact: true }).click()]);
console.log("  downloaded", dl.suggestedFilename());
// reload keeps the text
await page.reload();
await page.locator("textarea[id^=text-]").waitFor();
const kept = await page.locator("textarea[id^=text-]").inputValue();
if (!kept.startsWith("Large language models")) throw new Error("text not persisted");

step("links: triage changes update the guide and themes; ask about a theme");
await page.getByRole("link", { name: /^Papers/ }).click();
for (let i = 0; i < 3; i++) {
  await page.getByRole("button", { name: "Remove", exact: true }).first().click();
  await page.getByText(/removed\./).waitFor();
  await page.getByRole("button", { name: "Dismiss" }).last().click();
}
await page.getByRole("link", { name: /^Write/ }).click();
await page.getByText(/Guide updated: .*papers were removed/).waitFor({ timeout: 60_000 });
const still = await page.locator("textarea[id^=text-]").inputValue();
if (!still.startsWith("Large language models")) throw new Error("guide refresh touched the user's text");
await page.getByRole("button", { name: "Ask about this section" }).click();
await partner.getByText("Section: Introduction").waitFor();
await shot("07b-guide-updated");
await page.getByRole("link", { name: /^Explore/ }).click();
await page.getByText(/Updated for your changes/).waitFor({ timeout: 60_000 });
await page.getByRole("button", { name: "Ask about this theme" }).first().click();
await partner.getByText(/^Theme: /).waitFor();
await partner.getByText(/What do the papers in the/).waitFor();
await partner.getByText(/Sources \(/).last().waitFor({ timeout: 30_000 });
await shot("07c-theme-partner");
await partner.getByRole("button", { name: "Close research partner" }).click();

step("old links still work");
await page.goto(page.url().replace(/\/explore\/themes.*/, "/gaps"));
await page.waitForURL(/\/explore\/gaps/);

step("share");
await page.getByRole("link", { name: "Share" }).last().click();
await page.getByRole("heading", { name: "People with access" }).waitFor();
await shot("08-share");

step("mobile");
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("link", { name: /^Explore/ }).click();
await page.getByRole("link", { name: /^Gaps/ }).click();
await page.waitForTimeout(400);
await shot("09-mobile-gaps");
await page.getByRole("button", { name: "Research partner" }).click();
await page.getByRole("complementary", { name: "Research partner" }).waitFor();
await shot("09b-mobile-partner");
await page.getByRole("button", { name: "Close research partner" }).click();

step("logout");
await page.setViewportSize({ width: 1440, height: 1000 });
await page.getByRole("button", { name: "Log out" }).click();
await page.getByRole("heading", { name: "Welcome back" }).waitFor();

await browser.close();
// 401s are the expected "not logged in" check on /me.
const real = errors.filter((e) => !/favicon|status of 401/.test(e));
if (real.length) { console.log("Console errors:\n" + real.join("\n")); process.exit(1); }
console.log("All steps passed, no console errors.");
