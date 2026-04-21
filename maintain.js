import { OpenAI } from 'openai';
import fs from 'fs';
import path from 'path';

const openai = new OpenAI({
  apiKey: process.env.POE_API_KEY,
  baseURL: 'https://api.poe.com/v1',
});

async function getSchemaAndIndex() {
  const schema = fs.readFileSync('wiki/schema.md', 'utf8');
  let index = '# World Model Index\n\n';
  try { index = fs.readFileSync('wiki/index.md', 'utf8'); } catch {}
  return { schema, index };
}

async function main() {
  console.log('🔄 Starting world model maintenance...');

  const { schema, index } = await getSchemaAndIndex();

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

Output ONLY a valid JSON array like this (no extra text, no markdown code blocks):
[
  {"path": "wiki/some-page.md", "content": "full markdown here"},
  {"path": "wiki/index.md", "content": "..."},
  {"path": "wiki/log.md", "content": "..."}
]`;

  const completion = await openai.chat.completions.create({
    model: "Gemini-3.1-Pro",
    messages: [{ role: "user", content: prompt }],
    temperature: 0.3,
    max_tokens: 32000,
  });

  let jsonStr = completion.choices[0].message.content.trim();
  // Clean common LLM wrappers
  jsonStr = jsonStr.replace(/```json\n?/g, '').replace(/```\n?/g, '');

  const updates = JSON.parse(jsonStr);

  for (const update of updates) {
    const fullPath = update.path;
    fs.mkdirSync(path.dirname(fullPath), { recursive: true });
    fs.writeFileSync(fullPath, update.content, 'utf8');
    console.log(`✅ Wrote ${fullPath}`);
  }

  console.log('✅ All files written. Git commit will happen next in workflow.');
}

main().catch(e => {
  console.error('❌ Error:', e);
  process.exit(1);
});
