import { OpenAI } from 'openai';
import { Octokit } from '@octokit/rest';
import fs from 'fs';
import path from 'path';

const openai = new OpenAI({
  apiKey: process.env.POE_API_KEY,
  baseURL: 'https://api.poe.com/v1',
});

const octokit = new Octokit({ auth: process.env.GITHUB_TOKEN });
const OWNER = process.env.GITHUB_REPOSITORY.split('/')[0];
const REPO = process.env.GITHUB_REPOSITORY.split('/')[1];

async function getSchemaAndIndex() {
  const schema = fs.readFileSync('wiki/schema.md', 'utf8');
  const index = fs.readFileSync('wiki/index.md', 'utf8') || '# World Model Index\n\n';
  return { schema, index };
}

async function main() {
  console.log('🔄 Starting world model maintenance...');

  const { schema, index } = await getSchemaAndIndex();

  // Get new/changed sources
  const sources = fs.readdirSync('sources')
    .filter(f => f.endsWith('.md'))
    .map(f => ({
      name: f,
      content: fs.readFileSync(`sources/${f}`, 'utf8')
    }));

  if (sources.length === 0) {
    console.log('No new sources. Running health check...');
  }

  const prompt = `
${schema}

CURRENT INDEX:
${index}

NEW/UPDATED SOURCES:
${sources.map(s => `--- FILE: ${s.name} ---\n${s.content}\n`).join('\n')}

Output ONLY a valid JSON array of file updates:
[
  {"path": "wiki/some-page.md", "content": "full markdown here"},
  {"path": "wiki/index.md", "content": "..."},
  {"path": "wiki/log.md", "content": "..."}
]
Never add extra text.`;

  const completion = await openai.chat.completions.create({
    model: "Gemini-3.1-Pro",        // ← change here or make dynamic
    messages: [{ role: "user", content: prompt }],
    temperature: 0.3,
    max_tokens: 32000,
  });

  const jsonStr = completion.choices[0].message.content.trim();
  const updates = JSON.parse(jsonStr);

  // Apply updates
  for (const update of updates) {
    const fullPath = update.path;
    fs.mkdirSync(path.dirname(fullPath), { recursive: true });
    fs.writeFileSync(fullPath, update.content);
    console.log(`✅ Updated ${fullPath}`);
  }

  // Commit & push
  await octokit.repos.createOrUpdateFiles({
    owner: OWNER,
    repo: REPO,
    branch: 'main',
    changes: updates.map(u => ({
      path: u.path,
      content: Buffer.from(u.content).toString('base64'),
      encoding: 'base64',
    })),
    message: `🤖 World model update - ${new Date().toISOString()}`,
  });

  console.log('✅ World model updated successfully!');
}

main().catch(console.error);