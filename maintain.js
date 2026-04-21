import { OpenAI } from 'openai';
import fs from 'fs';
import path from 'path';

const openai = new OpenAI({
  apiKey: process.env.POE_API_KEY,
  baseURL: 'https://api.poe.com/v1',
});

async function main() {
  console.log('🔄 Starting world model maintenance...');

  let schema = '# Schema not found';
  let index = '# World Model Index\n\n';
  try { schema = fs.readFileSync('wiki/schema.md', 'utf8'); } catch {}
  try { index = fs.readFileSync('wiki/index.md', 'utf8'); } catch {}

  const sources = fs.readdirSync('sources')
    .filter(f => f.endsWith('.md'))
    .map(f => ({
      name: f,
      content: fs.readFileSync(`sources/${f}`, 'utf8')
    }));

  const prompt = `
${schema}

CURRENT INDEX:
${index}

NEW OR UPDATED SOURCES:
${sources.map(s => `--- FILE: ${s.name} ---\n${s.content}\n`).join('\n') || 'No new sources this run.'}

Output **ONLY** a valid JSON array. No extra text, no \`\`\`json, no explanation.
Example:
[
  {"path": "wiki/kool-limited.md", "content": "# kool limited\\n\\nUpdated content here..."},
  {"path": "wiki/index.md", "content": "updated index..."},
  {"path": "wiki/log.md", "content": "update log..."}
]`;

  const completion = await openai.chat.completions.create({
    model: "Gemini-3.1-Pro",
    messages: [{ role: "user", content: prompt }],
    temperature: 0.2,
    max_tokens: 32000,
  });

  let jsonStr = completion.choices[0].message.content.trim();
  // Clean common LLM wrappers
  jsonStr = jsonStr.replace(/```json\n?/gi, '').replace(/```\n?/gi, '').trim();

  console.log('Raw LLM output (first 500 chars):', jsonStr.substring(0, 500));

  let updates;
  try {
    updates = JSON.parse(jsonStr);
  } catch (e) {
    console.error('❌ JSON parse failed. Raw output:', jsonStr);
    throw e;
  }

  for (const update of updates) {
    if (!update.path || !update.content) continue;
    const fullPath = update.path;
    fs.mkdirSync(path.dirname(fullPath), { recursive: true });
    fs.writeFileSync(fullPath, update.content, 'utf8');
    console.log(`✅ Wrote file: ${fullPath}`);
  }

  console.log('✅ Files written. Git commit step will run next.');
}

main().catch(e => {
  console.error('❌ Error in maintain.js:', e.message);
  process.exit(1);
});
