/**
 * VS Code host for the Finance Memory SDK.
 *
 * The same `finance-memory.mjs` that runs in the browser runs here — this file
 * only wires it to VS Code's command palette and persists memories to disk, so
 * nothing about your finances leaves the machine.
 *
 * Educational only: every result carries the not-advice disclaimer.
 */

const fs = require('fs');
const path = require('path');
const vscode = require('vscode');

const SDK_PATH = path.join(__dirname, '..', 'js', 'finance-memory.mjs');

let sdk = null;
let storageFile = null;
let output = null;

async function loadSdk(context) {
  if (sdk) return sdk;
  const { FinanceMemorySDK } = await import(`file://${SDK_PATH}`);
  const config = vscode.workspace.getConfiguration('financeMemory');
  storageFile =
    config.get('storagePath') || path.join(context.globalStorageUri.fsPath, 'memory.json');
  fs.mkdirSync(path.dirname(storageFile), { recursive: true });
  sdk = new FinanceMemorySDK({ subject: config.get('subject') || 'user' });
  if (fs.existsSync(storageFile)) {
    try {
      sdk.importRecords(JSON.parse(fs.readFileSync(storageFile, 'utf8')));
    } catch {
      vscode.window.showWarningMessage('Finance Advisor: memory file unreadable, starting fresh.');
    }
  }
  return sdk;
}

function persist() {
  if (!sdk || !storageFile) return;
  fs.writeFileSync(storageFile, JSON.stringify(sdk.export(), null, 2));
}

function show(title, payload) {
  output = output || vscode.window.createOutputChannel('Finance Advisor');
  output.appendLine(`\n=== ${title} — ${new Date().toLocaleString()} ===`);
  output.appendLine(typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2));
  output.show(true);
}

const SKILL_PROMPTS = {
  loans: [
    ['principal', 'Loan principal (₹)', '3500000'],
    ['annualRatePct', 'Interest rate % p.a.', '8.6'],
    ['months', 'Tenure in months', '240'],
  ],
  mutual_funds: [
    ['monthly', 'Monthly SIP (₹)', '25000'],
    ['years', 'Years invested', '15'],
    ['annualReturnPct', 'Assumed return % p.a.', '12'],
  ],
  crypto: [
    ['portfolioValue', 'Total portfolio value (₹)', '2000000'],
    ['riskTolerance', 'conservative | moderate | aggressive', 'moderate'],
  ],
  capital_gains: [
    ['buyValue', 'Purchase value (₹)', '500000'],
    ['sellValue', 'Sale value (₹)', '800000'],
    ['holdingMonths', 'Months held', '18'],
  ],
  taxes: [
    ['regime', 'Tax regime: old | new', 'new'],
    ['existing80c', '80C already used (₹)', '0'],
  ],
};

async function collectArgs(skillName) {
  const args = {};
  for (const [key, prompt, value] of SKILL_PROMPTS[skillName] || []) {
    const answer = await vscode.window.showInputBox({ prompt, value, ignoreFocusOut: true });
    if (answer === undefined) return null; // user cancelled
    const numeric = Number(answer);
    args[key] = Number.isNaN(numeric) || answer.trim() === '' ? answer : numeric;
  }
  return args;
}

/** VS Code entry point: register the five commands. */
function activate(context) {
  const register = (id, handler) =>
    context.subscriptions.push(vscode.commands.registerCommand(id, handler));

  register('financeMemory.ask', async () => {
    const instance = await loadSdk(context);
    const query = await vscode.window.showInputBox({
      prompt: 'Ask about your finances (searches your local memory)',
      placeHolder: 'e.g. what did I say my take-home was?',
      ignoreFocusOut: true,
    });
    if (!query) return;
    const hits = instance.recall(query, 5);
    show(
      `Recall: ${query}`,
      hits.length ? hits : 'No memories yet — run "Remember a fact" first.',
    );
    persist();
  });

  register('financeMemory.remember', async () => {
    const instance = await loadSdk(context);
    const content = await vscode.window.showInputBox({
      prompt: 'Fact to remember (use key=value for profile facts)',
      placeHolder: 'e.g. take_home=180000',
      ignoreFocusOut: true,
    });
    if (!content) return;
    const type = await vscode.window.showQuickPick(
      ['semantic', 'episodic', 'working', 'procedural', 'graph'],
      { placeHolder: 'Memory type' },
    );
    if (!type) return;
    const sensitive = await vscode.window.showQuickPick(['no', 'yes'], {
      placeHolder: 'Sensitive (redact in exports and prompts)?',
    });
    instance.remember(content, {
      type,
      tags: content.includes('=') ? ['profile'] : [],
      sensitive: sensitive === 'yes',
    });
    persist();
    vscode.window.showInformationMessage(`Finance Advisor: remembered (${type}).`);
  });

  register('financeMemory.runSkill', async () => {
    const instance = await loadSdk(context);
    const skillName = await vscode.window.showQuickPick(Object.keys(SKILL_PROMPTS), {
      placeHolder: 'Which skill?',
    });
    if (!skillName) return;
    const args = await collectArgs(skillName);
    if (args === null) return;
    show(`Skill: ${skillName}`, instance.advise(skillName, args));
    persist();
  });

  register('financeMemory.showRuntimes', async () => {
    const { FinanceMemorySDK } = await import(`file://${SDK_PATH}`);
    show('Local runtimes', {
      capabilities: FinanceMemorySDK.capabilities(),
      runtimes: FinanceMemorySDK.runtimes(),
    });
  });

  register('financeMemory.exportMemory', async () => {
    const instance = await loadSdk(context);
    const doc = await vscode.workspace.openTextDocument({
      language: 'json',
      content: JSON.stringify(instance.export(), null, 2),
    });
    vscode.window.showTextDocument(doc);
  });
}

/** VS Code teardown: flush memories to disk. */
function deactivate() {
  persist();
}

module.exports = { activate, deactivate };
