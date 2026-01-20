"""
KOI RID Types - Blockchain/Ledger Entities
ORN classes for Regen Ledger credit classes, projects, organizations, and batches.
"""

from koi_protocol.core.rid_system import ORN


class RegenCreditClassRID(ORN):
    """
    Credit Class RID: orn:regen.credit_class:C02

    Used for Regen Ledger credit classes (e.g., C01, C02, BT01).
    """
    namespace = "regen.credit_class"

    def __init__(self, class_id: str):
        self.class_id = class_id
        super().__init__()

    @property
    def reference(self) -> str:
        return self.class_id


class RegenProjectRID(ORN):
    """
    Project RID: orn:regen.project:C02-003

    Used for Regen Ledger projects (e.g., C02-001, BT01-002).
    """
    namespace = "regen.project"

    def __init__(self, project_id: str):
        self.project_id = project_id
        super().__init__()

    @property
    def reference(self) -> str:
        return self.project_id


class RegenOrganizationRID(ORN):
    """
    Organization RID: orn:regen.organization:regen123a7e9g

    Used for organizations that administer credit classes/projects.
    Uses the first 15 characters of the admin address as identifier.
    """
    namespace = "regen.organization"

    def __init__(self, admin_prefix: str):
        self.admin_prefix = admin_prefix
        super().__init__()

    @property
    def reference(self) -> str:
        return self.admin_prefix


class RegenBatchRID(ORN):
    """
    Batch RID: orn:regen.batch:C02-001-20220101-20221231-001

    Used for credit batches with their full denomination.
    """
    namespace = "regen.batch"

    def __init__(self, batch_denom: str):
        self.batch_denom = batch_denom
        super().__init__()

    @property
    def reference(self) -> str:
        return self.batch_denom


class RegenGovernanceProposalRID(ORN):
    """
    Governance Proposal RID: orn:regen.proposal:42

    Used for on-chain governance proposals.
    """
    namespace = "regen.proposal"

    def __init__(self, proposal_id: str):
        self.proposal_id = str(proposal_id)
        super().__init__()

    @property
    def reference(self) -> str:
        return self.proposal_id


class RegenValidatorRID(ORN):
    """
    Validator RID: orn:regen.validator:regenvaloper1...

    Used for validators on the Regen Network.
    """
    namespace = "regen.validator"

    def __init__(self, validator_address: str):
        self.validator_address = validator_address
        super().__init__()

    @property
    def reference(self) -> str:
        return self.validator_address
