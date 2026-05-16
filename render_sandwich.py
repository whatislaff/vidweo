import sys
import json
import subprocess
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def format_path_for_ffmpeg_subtitles(filepath):
    """
    FFmpeg subtitles filter requires special path escaping on Windows.
    Example: C:\path\to\subs.srt -> C\:/path/to/subs.srt
    """
    p = filepath.replace('\\', '/')
    p = p.replace(':', '\\:')
    return p

def format_srt_to_ass(input_srt, output_ass, video_width=1080, video_height=1920):
    try:
        with open(input_srt, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    except Exception as e:
        print(f"[ERROR] Ошибка чтения субтитров: {e}")
        return

    blocks = content.strip().split('\n\n')
    
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00DCF5F5,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,10,10,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_events = []
    
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            timing = lines[1]
            if ' --> ' not in timing:
                continue
            start_str, end_str = timing.split(' --> ')
            start_ass = start_str[1:11].replace(',', '.')
            end_ass = end_str[1:11].replace(',', '.')
            
            text = " ".join(lines[2:]).replace('\n', ' ')
            words = text.split()
            new_text_lines = []
            for i in range(0, len(words), 4):
                new_text_lines.append(" ".join(words[i:i+4]))
                
            ass_text = "\\N".join(new_text_lines)
            ass_events.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{{\\fad(200,200)}}{ass_text}")

    with open(output_ass, 'w', encoding='utf-8') as f:
        f.write(ass_header)
        f.write("\n".join(ass_events))
        f.write("\n")

def time_str_to_seconds(time_str):
    """Converts 'HH:MM:SS' or 'HH:MM:SS.mmm' to seconds."""
    parts = str(time_str).split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(time_str)

def get_video_duration(filepath):
    """Uses ffprobe to get video duration in seconds."""
    cmd = [
        "ffprobe", 
        "-v", "error", 
        "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        filepath
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"[ERROR] Не удалось получить длительность видео {filepath}: {e}")
        return 0.0

def main():
    config = {}
    if len(sys.argv) >= 2:
        config_path = sys.argv[1]
        if not os.path.exists(config_path):
            print(f"[ERROR] Файл конфигурации не найден: {config_path}")
            sys.exit(1)
        with open(config_path, 'r', encoding='utf-8') as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[ERROR] Ошибка парсинга JSON: {e}")
                sys.exit(1)
    else:
        print("[INFO] Запуск без конфига. Читаем broll.json и ищем файлы в текущей папке...")
        if not os.path.exists("broll.json"):
            print("[ERROR] Файл broll.json не найден!")
            sys.exit(1)
            
        with open("broll.json", 'r', encoding='utf-8') as f:
            broll_data = json.load(f)
            
        inner_json_str = broll_data[0].get("output", "[]")
        b_rolls_parsed = json.loads(inner_json_str)
        
        b_rolls_config = []
        for item in b_rolls_parsed:
            b_rolls_config.append({
                "path": f"{item.get('query', '')}.mp4",
                "start": item.get("start", "00:00:00")
            })
            
        config = {
            "avatar_video": "avatar.mp4",
            "b_rolls": b_rolls_config,
            "subtitles": "srt.srt",
            "output": "output.mp4"
        }

    avatar_path = config.get("avatar_video")
    b_rolls = config.get("b_rolls", [])
    subtitles_path = config.get("subtitles")
    output_path = config.get("output", "output.mp4")

    if not avatar_path or not b_rolls:
        print("[ERROR] Поля 'avatar_video' и 'b_rolls' обязательны в конфиге.")
        sys.exit(1)

    print(f"[INFO] Начинаем сборку видео {output_path}...")

    ffmpeg_cmd = ["ffmpeg", "-y"]
    
    # Вход 0: Аватар (содержит аудио и видео с зеленым фоном)
    ffmpeg_cmd.extend(["-i", avatar_path])
    
    # Входы 1..N: B-Roll'ы
    for b in b_rolls:
        ffmpeg_cmd.extend(["-i", b["path"]])

    filter_complex = []
    
    # Обработка B-rolls
    num_brolls = len(b_rolls)
    concat_inputs = ""
    
    # Получаем общую длительность аватара для расчета длины последнего B-Roll
    avatar_duration = get_video_duration(avatar_path)
    if avatar_duration <= 0:
        print("[WARNING] Не удалось определить длительность аватара, используем 60с по умолчанию.")
        avatar_duration = 60.0

    for i, b in enumerate(b_rolls):
        idx = i + 1  # индекс входа (0 - это аватар)
        
        start_str = b.get("start")
        if start_str is not None:
            current_start = time_str_to_seconds(start_str)
            if i + 1 < num_brolls:
                next_start = time_str_to_seconds(b_rolls[i+1].get("start", "0"))
                target_duration = next_start - current_start
            else:
                target_duration = avatar_duration - current_start
                
            if target_duration <= 0:
                target_duration = 3.0
        else:
            target_duration = 3.0

        actual_duration = get_video_duration(b["path"])
        if actual_duration <= 0:
            actual_duration = target_duration
            
        time_filter = ""
        if actual_duration > target_duration:
            time_filter = f"trim=duration={target_duration},"
        elif actual_duration < target_duration:
            factor = target_duration / actual_duration
            time_filter = f"setpts={factor}*PTS,"
            
        # Масштабируем и обрезаем под 1080x1920, сбрасываем таймстемпы
        f_str = f"[{idx}:v]{time_filter}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setpts=PTS-STARTPTS[v{idx}];"
        filter_complex.append(f_str)
        concat_inputs += f"[v{idx}]"

    # Склеиваем B-roll'ы
    filter_complex.append(f"{concat_inputs}concat=n={num_brolls}:v=1:a=0[bg];")

    # Обработка Аватара: вырезаем зеленый фон и масштабируем до 1/2 высоты (960px)
    filter_complex.append(f"[0:v]chromakey=0x00FF00:0.1:0.2,scale=-1:960[avatar_transparent];")

    # Накладываем аватара (слева внизу) и субтитры (по центру, 1/4 снизу)
    if subtitles_path and os.path.exists(subtitles_path):
        formatted_subs_path = "temp_subs_formatted.ass"
        format_srt_to_ass(subtitles_path, formatted_subs_path)
        
        esc_subs = format_path_for_ffmpeg_subtitles(formatted_subs_path)
        filter_complex.append(f"[bg][avatar_transparent]overlay=-108:H-h[v_composed];")
        filter_complex.append(f"[v_composed]subtitles='{esc_subs}'[outv]")
    else:
        filter_complex.append(f"[bg][avatar_transparent]overlay=-108:H-h[outv]")

    ffmpeg_cmd.extend([
        "-filter_complex", "".join(filter_complex),
        "-map", "[outv]",  # Выходное видео
        "-map", "0:a",     # Аудио берем из аватара
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ])

    print("[INFO] Выполняется команда FFmpeg:\n" + " ".join(ffmpeg_cmd))

    try:
        subprocess.run(ffmpeg_cmd, check=True)
        print(f"[SUCCESS] Видео успешно сохранено в {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Ошибка при рендере FFmpeg. Код завершения: {e.returncode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
