"""Optional evidence-collection experiments; these never change an assessment."""

EXPERIMENTS = {
    1: 'Check the selected project, date range, and log locations first. If you want to try AI assistance, use one bounded question and retain its activity log.',
    2: 'Try one reversible code change with AI editing, review the diff, and run an explicit acceptance check. Retain the activity and acceptance evidence.',
    3: 'Assign a bounded task with explicit acceptance criteria. Let the agent edit and attempt verification in the same session; record the outcome and human interventions. Collect representative activity, not extra calls to reach a threshold.',
    4: 'Repeat bounded tasks across sessions and days, retaining edit/verify activity, acceptance outcomes, and human interventions. Repetition alone does not prove successful delivery.',
    5: 'Try a controlled task queue with explicit acceptance checks and human control boundaries. Record task pickup, PR delivery, CI recovery, outcomes, and interventions. L5 remains unverified by this analyzer.',
}

EXPERIMENT_NOTE = 'An optional experiment to collect evidence, not a requirement to adopt more autonomy or proof of a higher level.'


def recommended_experiment(report):
    return EXPERIMENTS.get(report['next_target'])
