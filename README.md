# drive-check

Will this drive and this computer run a local AI model well? Point drive-check at a drive and a model file. It measures the drive's real read speed, estimates how long the model takes to load from it, and checks the model against your RAM. Then it prints one verdict and the sizes of Gemma that fit your computer.

It comes from The Coderlog video where I ran the same AI app from a USB SSD and from my Mac's own disk. The drive only changed how long I waited for a model to load. Once loaded, both answered at the same speed. RAM decided which models ran at all: an 18 GB model on a 16 GB Mac took almost eight minutes to load and crashed before it answered.

## Run it

You need Python 3.8 or newer. Nothing to install. It works on macOS, Windows and Linux.

```
python3 drive_check.py /Volumes/MyDrive --model /Volumes/MyDrive/models/gemma-4-E4B-it-Q4_K_M.gguf
```

On Windows:

```
py drive_check.py D:\ --model D:\models\gemma-4-E4B-it-Q4_K_M.gguf
```

Output from the video's Mac mini (M4, 16 GB), with the USB SSD first:

```
drive-check
  computer : Darwin arm64, RAM 16.0 GB (13.3 GB free now), room for a model: about 12.9 GB
  drive    : write 277 MB/s, read 311 MB/s
  drive    : read 400 MB/s from the model file
  model    : gemma-4-E4B-it-Q4_K_M.gguf (5.0 GB)
  verdict  : fine for this model (load about 15 s)
  ladder   : what fits this computer (load times from this drive)
    yes    Gemma 4 E2B Q4_K_M (3.1 GB), load about 11 s
    yes    Gemma 4 E4B Q4_K_M (5.0 GB), load about 15 s
    yes    Gemma 4 12B Q4_K_M (7.1 GB), load about 21 s
    no     Gemma 4 31B Q4_K_M (18.3 GB)
  RAM decides which model you can run. The drive decides how long you wait for it to load.
```

The same model on the Mac's internal disk:

```
drive-check
  computer : Darwin arm64, RAM 16.0 GB (13.3 GB free now), room for a model: about 12.9 GB
  drive    : write 1888 MB/s, read 2970 MB/s
  drive    : read 1786 MB/s from the model file
  model    : gemma-4-E4B-it-Q4_K_M.gguf (5.0 GB)
  verdict  : fine for this model (load about 6 s)
  ladder   : what fits this computer (load times from this drive)
    yes    Gemma 4 E2B Q4_K_M (3.1 GB), load about 5 s
    yes    Gemma 4 E4B Q4_K_M (5.0 GB), load about 6 s
    yes    Gemma 4 12B Q4_K_M (7.1 GB), load about 7 s
    no     Gemma 4 31B Q4_K_M (18.3 GB)
  RAM decides which model you can run. The drive decides how long you wait for it to load.
```

The estimates were close to the real loads I timed in the app: 15 s estimated against 14.7 s measured from the USB SSD, and 6 s against 5.2 s from the Mac's disk.

## Options

| Option | What it does |
|---|---|
| `--model FILE` | Reads a model file on the drive to get the real read speed, and gives a verdict for that model. |
| `--size-mb N` | Size of the write test (default 1024 MB). The test file is deleted afterwards. |
| `--no-write` | Skips the write test, for read-only drives. |
| `--llama-bench EXE` | Runs llama.cpp's `llama-bench` on the model to add tokens per second. |
| `--json` | Prints everything as JSON. |

## How it decides

A model fits when its file plus about 1.5 GB (context, cache and the engine) is under 75% of your RAM. That is roughly what macOS lets the GPU use on a 16 GB Mac (12.7 GB on my M4). Between 75% and 100% it says "tight": the model may load, but the computer will swap and answers will crawl. Over 100% it says "no".

The load time estimate is the file size divided by the drive's read speed, plus 3 seconds to start the engine. Those 3 seconds were measured on an M4.

For a true read speed, read a model file the computer hasn't opened since it started, or unplug and re-plug the drive first. On a Mac, `sudo purge` clears the file cache. Windows can serve a file it just wrote from memory, so use `--model` there.

## Results from the video

Mac mini M4, 16 GB. Same app (Portable Local Studio), same model files, cold loads, 5 runs each.

| | USB SSD (SanDisk Extreme Portable) | Mac's internal disk |
|---|---|---|
| Load Gemma 4 E4B (5 GB) | 14.7 s | 5.2 s |
| Answer speed | 25.4 tokens/s | 25.7 tokens/s |
| Image, 20 steps | 32.2 s | 32.2 s |
| Whole job (load, chat, image, transcribe, speak) | 68.4 s | 55.7 s |

Ladder, loaded from the USB SSD:

| Model | File | Load | Tokens/s |
|---|---|---|---|
| Gemma 4 E2B | 3.1 GB | 9.7 s | 47.6 |
| Gemma 4 E4B | 5.0 GB | 14.7 s | 25.7 |
| Gemma 4 12B | 7.1 GB | 20.7 s | 11.8 |
| Gemma 4 31B | 18.3 GB | 7 min 43 s | crashed before answering |

Tell me your drive, your RAM and your load time in the video's comments.

## Licence

MIT
