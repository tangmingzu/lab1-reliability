import argparse
import json
import csv
import os
import math

def calculate_reliability(lambda_val, time):
    return math.exp(-lambda_val * time)

def calculate_series_reliability(component_reliabilities):
    rel = 1.0
    for r in component_reliabilities:
        rel *= r
    return rel

def calculate_parallel_reliability(component_reliabilities):
    fail = 1.0
    for r in component_reliabilities:
        fail *= (1 - r)
    return 1 - fail

def calculate_rbd_reliability(rbd_struct, comp_rel):
    if isinstance(rbd_struct, str):
        return comp_rel.get(rbd_struct, 0.0)
    if "series" in rbd_struct:
        parts = [calculate_rbd_reliability(p, comp_rel) for p in rbd_struct["series"]]
        return calculate_series_reliability(parts)
    if "parallel" in rbd_struct:
        parts = [calculate_rbd_reliability(p, comp_rel) for p in rbd_struct["parallel"]]
        return calculate_parallel_reliability(parts)
    return 0.0

def calculate_subsystem_reliability(phases_rbd, comp_rel):
    res = {}
    for phase, rbd in phases_rbd.items():
        res[phase] = calculate_rbd_reliability(rbd, comp_rel)
    return res

def read_mission_profile(path):
    profile = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        comps = reader.fieldnames[2:]
        for row in reader:
            stage = row['Stage']
            dur = float(row['Duration_h'])
            work = {c: int(row[c]) for c in comps}
            profile[stage] = {'duration': dur, 'components': work}
    return profile, comps

def read_components(path):
    comps = {}
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row['Component']
            lam = float(row['Lambda (1/h)'])
            comps[name] = lam
    return comps

def read_model(path):
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def run_sanity_checks(profile, comps, model, N):
    total_cycle = sum(p['duration'] for p in profile.values())

    work_time = {}
    for c in comps:
        t = 0
        for phase in profile.values():
            t += phase['duration'] * phase['components'].get(c, 0)
        work_time[c] = t * N

    rel = {c: calculate_reliability(comps[c], work_time[c]) for c in comps}

    phase_rel = {}
    for ph, rbd in model['mission_phases'].items():
        phase_rel[ph] = calculate_rbd_reliability(rbd, rel)
    sys_rel = calculate_series_reliability(list(phase_rel.values()))

    def simplify(rbd):
        if isinstance(rbd, dict):
            if 'parallel' in rbd:
                return rbd['parallel'][0]
            if 'series' in rbd:
                return {'series': [simplify(s) for s in rbd['series']]}
        return rbd

    simple_model = {}
    for ph, rbd in model['mission_phases'].items():
        simple_model[ph] = simplify(rbd)
    simple_ph_rel = {ph: calculate_rbd_reliability(simple_model[ph], rel) for ph in simple_model}
    simple_sys = calculate_series_reliability(list(simple_ph_rel.values()))

    check1 = simple_sys <= sys_rel + 1e-9

    half_work = {c: wt/2 for c, wt in work_time.items()}
    half_rel = {c: calculate_reliability(comps[c], half_work[c]) for c in comps}
    half_ph_rel = {ph: calculate_rbd_reliability(model['mission_phases'][ph], half_rel) for ph in model['mission_phases']}
    half_sys = calculate_series_reliability(list(half_ph_rel.values()))
    check2 = half_sys > sys_rel - 1e-9

    return {'去冗余可靠度下降': check1, '任务缩短可靠度上升': check2}, sys_rel

def generate_report(sid, name, N, profile, comps, model, sys_rel, sub_rel, checks):
    os.makedirs('output', exist_ok=True)
    fn = f'output/lab1_report_{sid}_{name}.md'

    total_cycle = sum(p['duration'] for p in profile.values())
    total_time = total_cycle * N

    work_time = {}
    duty = {}
    comp_rel = {}
    for c in comps:
        t = 0
        for ph in profile.values():
            t += ph['duration'] * ph['components'].get(c, 0)
        t_total = t * N
        work_time[c] = t_total
        duty[c] = t_total / total_time if total_time > 0 else 0
        comp_rel[c] = calculate_reliability(comps[c], t_total)

    with open(fn, 'w', encoding='utf-8') as f:
        f.write('# 实验1：完整搬运循环任务可靠度评估\n')
        f.write(f'学号：{sid} 姓名：{name}\n\n')

        f.write('## 1. 任务参数\n')
        f.write(f'- 循环次数 N = {N}\n')
        f.write(f'- 单循环时长 = {total_cycle:.3f} h\n')
        f.write(f'- 总任务时长 = {total_time:.3f} h\n\n')

        f.write('## 2. 任务剖面\n')
        f.write('| 阶段 | 时长(h) | 工作元件 |\n')
        f.write('|------|---------|----------|\n')
        for ph, d in profile.items():
            ws = [c for c, v in d['components'].items() if v == 1]
            f.write(f'| {ph} | {d["duration"]:.2f} | {", ".join(ws)} |\n')
        f.write('\n')

        f.write('## 3. 元件工作时间与占空比\n')
        f.write('| 元件 | λ(1/h) | 总工作时间(h) | 占空比 | 可靠度 |\n')
        f.write('|------|--------|---------------|--------|--------|\n')
        for c in comps:
            f.write(f'| {c} | {comps[c]:.6f} | {work_time[c]:.3f} | {duty[c]:.2f} | {comp_rel[c]:.6f} |\n')
        f.write('\n')

        f.write('## 4. RBD结构\n```json\n')
        json.dump(model, f, indent=2, ensure_ascii=False)
        f.write('\n```\n\n')

        f.write('## 5. 各阶段子系统可靠度\n')
        f.write('| 阶段 | 可靠度 |\n|------|--------|\n')
        for ph, r in sub_rel.items():
            f.write(f'| {ph} | {r:.6f} |\n')
        f.write('\n')

        f.write('## 6. 系统总可靠度\n')
        f.write(f'系统可靠度 = {sys_rel:.6f}\n\n')

        f.write('## 7. 合理性检查\n')
        for chk, ok in checks.items():
            f.write(f'- {chk}：{"通过" if ok else "失败"}\n')
        f.write('\n')

        f.write('## 8. 学生自定义补充区\n')
        f.write('### 建模思路\n')
        f.write('任务分为Pick/Lift/TravelLoaded/Place/ReturnEmpty五阶段，电源、PLC、安全链全程工作；提升电机设置并联冗余，其余元件按动作阶段工作。\n\n')
        f.write('### AI使用与核验\n')
        f.write('AI最初将并联可靠度写成平均值，经手动用双元件案例验算后，修正为标准并联公式：R=1−∏(1−Ri)，确保计算正确。\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--student_id', required=True)
    parser.add_argument('--student_name', required=True)
    parser.add_argument('--N', type=int, default=60)
    args = parser.parse_args()

    profile, _ = read_mission_profile('data/mission_profile.csv')
    comps = read_components('data/components.csv')
    model = read_model('data/model.json')

    checks, sys_rel = run_sanity_checks(profile, comps, model, args.N)

    total_cycle = sum(p['duration'] for p in profile.values())
    work_time = {}
    for c in comps:
        t = 0
        for ph in profile.values():
            t += ph['duration'] * ph['components'].get(c, 0)
        work_time[c] = t * args.N
    comp_rel = {c: calculate_reliability(comps[c], work_time[c]) for c in comps}
    sub_rel = calculate_subsystem_reliability(model['mission_phases'], comp_rel)

    generate_report(args.student_id, args.student_name, args.N,
                    profile, comps, model, sys_rel, sub_rel, checks)

    print('报告已生成到 output 文件夹')
    print('合理性检查结果：', checks)

if __name__ == '__main__':
    main()
