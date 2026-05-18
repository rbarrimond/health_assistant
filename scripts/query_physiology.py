import urllib.request
import json

def get_json(url):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())

def main():
    athlete_id = "rob"
    base_url = "http://localhost:7071/api"
    
    # 1) Get current physiometrics
    try:
        physio = get_json(f"{base_url}/physiometrics/current?athlete_id={athlete_id}")
        hr = physio.get("heart_rate", {})
        lthr_bpm = hr.get("lthr_bpm")
        lthr_cycling_bpm = hr.get("lthr_cycling_bpm")
        print(f"Current Physiometrics: lthr_bpm={lthr_bpm}, lthr_cycling_bpm={lthr_cycling_bpm}")
    except Exception as e:
        print(f"Error fetching physiometrics: {e}")
        return

    # 2) Get workouts
    try:
        workouts_list = get_json(f"{base_url}/workouts?athlete_id={athlete_id}&limit=60")
        # Handle cases where response might be a dict containing the list
        if isinstance(workouts_list, dict):
            workouts_list = workouts_list.get("workouts", workouts_list.get("data", []))
    except Exception as e:
        print(f"Error fetching workouts list: {e}")
        return
    
    cycling_workouts = []
    non_cycling_workouts = []
    
    # 3) Fetch details
    for w in workouts_list:
        if len(cycling_workouts) >= 2 and len(non_cycling_workouts) >= 2:
            break
            
        try:
            w_id = w.get("workout_id")
            if not w_id:
                continue
            detail = get_json(f"{base_url}/workouts/{w_id}?athlete_id={athlete_id}")
            
            zones_hr = detail.get("zones_hr")
            if not zones_hr:
                continue
                
            sport = detail.get("sport", "")
            workout_info = {
                "workout_id": w_id,
                "sport": sport,
                "start_time_utc": detail.get("start_time_utc"),
                "hr_zone_basis": zones_hr.get("hr_zone_basis"),
                "hr_zone_reference_bpm": zones_hr.get("hr_zone_reference_bpm")
            }
            
            if sport == "cycling":
                if len(cycling_workouts) < 2:
                    cycling_workouts.append(workout_info)
            else:
                if len(non_cycling_workouts) < 2:
                    non_cycling_workouts.append(workout_info)
        except Exception as e:
            continue

    # 4) Print results
    all_sampled = cycling_workouts + non_cycling_workouts
    for sw in all_sampled:
        print(f"Workout: ID={sw['workout_id']}, Sport={sw['sport']}, Start={sw['start_time_utc']}, Basis={sw['hr_zone_basis']}, Ref={sw['hr_zone_reference_bpm']}")

    # 5) Verdict
    cycling_refs = set(w['hr_zone_reference_bpm'] for w in cycling_workouts if w['hr_zone_reference_bpm'] is not None)
    non_cycling_refs = set(w['hr_zone_reference_bpm'] for w in non_cycling_workouts if w['hr_zone_reference_bpm'] is not None)
    
    if cycling_workouts and non_cycling_workouts:
        common = cycling_refs.intersection(non_cycling_refs)
        if not common and cycling_refs and non_cycling_refs:
            print("Verdict: Cycling workouts consistently use a different reference than non-cycling.")
        elif common:
            print(f"Verdict: Inconsistent or overlapping references. Common refs: {common}")
        else:
            print("Verdict: Insufficient data (missing reference values) to compare cycling and non-cycling.")
    else:
        print("Verdict: Insufficient data to compare (missing either cycling or non-cycling samples).")

if __name__ == "__main__":
    main()
