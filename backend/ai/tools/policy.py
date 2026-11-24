"""The three name tables that decide what a tool call must ask, and who may see it at all.

They are data, and they are read by the host adapter and the coverage gate as well as by the engine,
which is why they live beside the specs rather than inside one domain module:

* ``UNIVERSAL_TOOLS`` — always offered, whatever skill was chosen;
* ``APPROVAL_TOOLS`` — a change on the user's machine or their run records, so an exact-call grant is
  required when auto-approve is off;
* ``ALWAYS_APPROVAL_TOOLS`` — deletions and a dataset grant, which auto-approve never covers.
"""

#: The product's always-offered vocabulary: every turn may read the project, its workflow files,
#: the working folder, propose an apply and ask for dataset rows, whatever skill was chosen.
UNIVERSAL_TOOLS = frozenset(
    {
        'ai_coverage',
        'app_errors',
        'export_delete',
        'export_list',
        'request_dataset_access',
        'rerun_node',
        'capability_catalog',
        'capability_load',
        'workflow_delete',
        'workflow_export',
        'workflow_list',
        'workflow_read',
        'workflow_rename',
        'workflow_run',
        'workflow_schema',
        'workflow_stop',
        'workflow_update',
        'workflow_validate',
        'workspace_info',
        'workspace_list',
        'workspace_read',
    }
)


#: Tools whose effect is a change on the user's machine or their run records. With
#: ``ai_auto_approve`` off, one of these runs only after the user answered a ``request_approval``
#: question with the EXACT arguments it is about to use (see ``ai.approvals``). ``workspace_set``
#: is deliberately absent: choosing a folder is a setting the panel offers, not a per-call act.
APPROVAL_TOOLS = (
    'run_cmd',
    'workspace_write',
    'workspace_import',
    'request_dataset_access',
    'rerun_node',
    'apply_codebook',
    'apply_node_result',
    'workflow_update',
    'workflow_rename',
    'workflow_delete',
    'workflow_export',
    'workflow_run',
    'export_delete',
)

#: Deletions are never covered by ``ai_auto_approve``: that switch means "do not ask me about your
#: usual work", not "let a model remove my files". A per-call grant is still required here. A
#: dataset grant is the same kind of act: it lets the model read the user's data, so it always
#: asks, even when the model proposed a modest row count.
ALWAYS_APPROVAL_TOOLS = frozenset({'workflow_delete', 'export_delete', 'request_dataset_access'})
