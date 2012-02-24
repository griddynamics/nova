# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Ken Pepple
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table
from nova import log as logging
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Enum
from nova.db.sqlalchemy.models import LocalVolume

meta = MetaData()

# Just for the ForeignKey and column creation to succeed, these are not the
# actual definitions of instances or services.
instances = Table('instances', meta,
    Column('id', Integer(), primary_key=True, nullable=False),
)

#
# New Tables
#
local_volumes = Table('local_volumes', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('user_id', String(255)),
        Column('project_id', String(255)),
        Column('snapshot_id', String(255)),
        Column('host', String(255)),
        Column('size', Integer),
        Column('instance_id', Integer(), ForeignKey('instances.id'), nullable=True),
        Column('mountpoint', String(255)),

        Column('attach_time', DateTime(timezone=False)),
        Column('scheduled_at', DateTime(timezone=False)),
        Column('launched_at', DateTime(timezone=False)),
        Column('terminated_at', DateTime(timezone=False)),

        Column('status', Enum(LocalVolume.CREATING, LocalVolume.AVAILABLE, LocalVolume.IN_USE,
            LocalVolume.ERROR, LocalVolume.DELETING, LocalVolume.ERROR_DELETING, LocalVolume.DELETED)),
        Column('attach_status', Enum(LocalVolume.ATTACHED, LocalVolume.DETACHED)),
        Column('device', String(255)),
        Column('display_description', String(255)),
        Column('volume_type_id', Integer))


def upgrade(migrate_engine):
    # Upgrade operations go here
    # Don't create your own engine; bind migrate_engine
    # to your metadata
    meta.bind = migrate_engine
    try:
        local_volumes.create()
    except Exception:
        logging.info(repr(local_volumes))
        logging.exception('Exception while creating instance_types table')
        raise


def downgrade(migrate_engine):
    # Operations to reverse the above upgrade go here.
    meta.bind = migrate_engine
    try:
        local_volumes.drop(migrate_engine)
    except Exception:
        logging.info(repr(local_volumes))
        logging.exception('Exception while dropping instance_types table')
        raise
