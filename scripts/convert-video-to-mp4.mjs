import { access, mkdir, readdir } from 'node:fs/promises'
import { join, extname, basename } from 'node:path'
import { spawn } from 'node:child_process'

const inputDir = process.argv[2] ?? 'test-results'
const outputDir = process.argv[3] ?? join(inputDir, 'mp4')
await mkdir(outputDir, { recursive: true })
const files = (await readdir(inputDir, { recursive: true })).filter((file) => extname(file) === '.webm')
if (!files.length) throw new Error(`No .webm files found under ${inputDir}`)
for (const relative of files) {
  const input = join(inputDir, relative)
  const output = join(outputDir, `${basename(relative, '.webm')}.mp4`)
  await access(input)
  await new Promise((resolve, reject) => {
    const ffmpeg = spawn('ffmpeg', ['-y', '-i', input, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', output], { stdio: 'inherit' })
    ffmpeg.on('error', () => reject(new Error('ffmpeg was not found on PATH; install ffmpeg to create MP4 files.')))
    ffmpeg.on('close', (code) => code === 0 ? resolve() : reject(new Error(`ffmpeg exited with code ${code}`)))
  })
}
