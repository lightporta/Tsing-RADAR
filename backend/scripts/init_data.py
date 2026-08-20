"""把证据化导师记录导入 advisors 表；隔离值不会写入业务列。"""

from app.db.session import SessionLocal, init_db
from app.models.advisor import Advisor
from app.services.data_loader import load_mentor_dataset


def main() -> None:
    init_db()
    dataset = load_mentor_dataset()

    db = SessionLocal()
    try:
        for record in dataset.records:
            fields = record.fields
            governance = record.governance
            advisor = Advisor(
                advisor_id=record.advisor_id,
                name=fields.get("name", ""),
                department=fields.get("dept", ""),
                field=fields.get("field", ""),
                tags=fields.get("tags", []),
                profile_text=None,
                recent_papers=None,
                contact_email=None,
                office_loc=None,
                radar_traits=None,
                popularity=None,
                sector=None,
                provenance={
                    key: [
                        entry.model_dump(mode="json", exclude_none=True)
                        for entry in entries
                    ]
                    for key, entries in record.provenance.items()
                },
                governance=governance.model_dump(
                    mode="json",
                    exclude_none=False,
                ),
                quarantined_fields={
                    key: value.model_dump(mode="json", exclude_none=False)
                    for key, value in record.quarantined_fields.items()
                },
                review_status=governance.review_status.value,
                publication_status=governance.publication_status.value,
                authorization_basis=governance.authorization.basis.value,
                consent_id=governance.authorization.consent_id,
                record_created_at=governance.created_at,
                record_updated_at=governance.updated_at,
                verified_at=governance.verified_at,
                expires_at=governance.expires_at,
                takedown_at=governance.takedown.effective_at,
            )
            db.merge(advisor)
        db.commit()
        print(
            f"imported={len(dataset.records)} "
            "publication_status=restricted_or_verified"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
