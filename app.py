        for idx, f in enumerate(uploaded_files):
            status_text.info(f"⚡ [{idx+1}/{len(uploaded_files)}] 正在由 **{LOCKED_MODEL}** 提取: `{f.name}` ...")
            try:
                raw_items = call_gemini_vision_direct(f.getvalue())
                for item in raw_items:
                    rows = split_and_explode_dates(
                        item.get("agency", "精选旅行社"),
                        item.get("destination", "精选路线"),
                        item.get("tour_code", "-"),
                        item.get("title", ""),
                        item.get("departure_location", ""),
                        item.get("departure_dates", ""),
                        item.get("price", 0)
                    )
                    newly_extracted.extend(rows)
            except Exception as e:
                has_error = True
                status_text.error(f"处理 {f.name} 时提示: {e}")

            progress_bar.progress((idx + 1) / len(uploaded_files))
