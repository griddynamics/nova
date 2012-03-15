import re
from nova import utils
from nova import quota
from nova import log
from nova import rpc
from nova import flags
from nova import exception
import nova
from nova.db import base
from nova import db

LOG = log.getLogger('nova.localvolume.api')

FLAGS = flags.FLAGS

class LocalAPI(base.Base):

    def __init__(self):
        super(LocalAPI, self).__init__()
        self.image_service = nova.image.get_default_image_service()

    def _call_compute(self, context, instance, method, args):
        return rpc.cast(context,
            self.db.queue_get_for(context, FLAGS.compute_topic,
                instance['host']), {
            'method': method,
            'args': args
        })

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id, local=True)
        return dict(rv.iteritems())

    def get_all(self, context):
        if context.is_admin:
            volumes = self.db.volume_get_all(context, local=True)
        else:
            volumes = self.db.volume_get_all_by_project(context,
                context.project_id, local=True)
        return volumes


    def get_snapshot(self, context, snapshot_id):
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def create_local(self, context, instance_id, device,
                           size, snapshot_id=None, description=None, volume_type=None, metadata=None):

        if not re.match("^/dev/[a-z]d[a-z]+$", device):
            raise exception.ApiError(_("Invalid device specified: %s. "
                                       "Example device: /dev/vdb") % device)

        instance = db.instance_get(context, instance_id)
        host = instance['host']
        LOG.debug('Snapshot id: %s' % snapshot_id)

        if snapshot_id is not None:
            image_info = self.image_service.show(context, snapshot_id)
            deleted = image_info['deleted']
            if deleted:
                raise exception.ApiError(_("Snapshot is deleted: %s") % snapshot_id)

            if not size:
                size = image_info['size']

        size = int(size)

        if quota.allowed_volumes(context, 1, size / (1024 * 1024 * 1024) ) < 1:
            pid = context.project_id
            LOG.warn(_("Quota exceeded for %(pid)s, tried to create"
                       " %(size)s volume") % locals())
            raise quota.QuotaError(_("Volume quota exceeded. You cannot "
                                     "create a volume of size %s") % size)

        if volume_type is None:
            volume_type_id = None
        else:
            volume_type_id = volume_type.get('id', None)

        options = {
            'instance_id': instance_id,
            'size': size,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'snapshot_id': snapshot_id,
            'display_description': description,
            'volume_type_id': volume_type_id,
            'metadata': metadata,
            'device': device,
            'status': "creating",
            'attach_status': 'detached'
            }

        volume = self.db.volume_create(context, options, local=True)

        self._call_compute(context, instance, 'create_local_volume', {
            "instance_id": instance_id,
            "device": device,
            "volume_id": volume['id'],
            "snapshot_id" : snapshot_id,
            "size": size
            })
        return volume

    def delete(self, context, volume_id):
        volume = self.db.volume_get(context, volume_id, local=True)
        now = utils.utcnow()

        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                               'terminated_at': now}, local=True)
        instance = self.db.instance_get(context, volume['instance_id'])
        self._call_compute(context, instance, 'delete_local_volume', {
            'volume_id': volume_id,
            })

    def resize(self, context, volume_id, new_size):
        volume = self.db.volume_get(context, volume_id, local=True)
        instance = self.db.instance_get(context, volume['instance_id'])
        self.db.volume_update(context, volume_id, {'size': new_size}, local=True)

        self._call_compute(context, instance, 'resize_local_volume', {
            'volume_id': volume_id,
            'new_size': new_size
        })

    def snapshot(self, context, volume_id, image_name, force_snapshot):
        volume = self.db.volume_get(context, volume_id, local=True)
        instance = self.db.instance_get(context, volume['instance_id'])

        properties = {
            'instance_uuid': instance['uuid'],
            'user_id': str(context.user_id),
            'image_state': 'creating',
            'image_type': 'snapshot',
        }

        metadata = self.image_service.create(context, {'name': image_name, 'is_public': False,
                                                       'status': 'creating', 'properties': properties})

        self._call_compute(context, instance, 'snapshot_local_volume', {
            'volume_name': volume['name'],
            'instance_id': instance['id'],
            'image_id': metadata['id'],
            'force_snapshot': force_snapshot
        })


