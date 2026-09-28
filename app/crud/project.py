from sqlalchemy.orm import Session, joinedload
from app.models.project import Project

def create_project(db: Session, project: Project) -> Project:
    db.add(project)
    db.commit()
    db.refresh(project)
    return project

def get_all_projects(db: Session):
    return db.query(Project).options(
        joinedload(Project.parts)
    ).all()

def get_project_by_id(db: Session, project_id: int):
    return db.query(Project).options(
        joinedload(Project.parts)
    ).filter(Project.id == project_id).first()

def update_project(db: Session, project: Project) -> Project:
    db.commit()
    db.refresh(project)
    return project

def delete_project(db: Session, project: Project):
    db.delete(project)
    db.commit()
