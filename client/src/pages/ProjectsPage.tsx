import {
  Title,
  Table,
  Group,
  Text,
  ActionIcon,
  Badge,
  Stack,
  Skeleton,
  Button,
  Pagination,
  TextInput,
  Select,
} from '@mantine/core';
import { useProjects } from '../hooks/useProjects';
import { IconEye, IconPencil, IconTrash } from '@tabler/icons-react';
import { Link } from 'react-router-dom';
import { formatDate } from '../utils/formatDate';
import { ProjectModal } from '../components/projects/ProjectModal';
import { useDisclosure } from '@mantine/hooks';
import { useState } from 'react';
import type { Project, ProjectStatus, ProjectType } from '../types';
import { useModals } from '@mantine/modals';
import { useDeleteProject } from '../hooks/useProjectMutations';

const statusColors: Record<string, string> = {
  draft: 'gray',
  selector_generated: 'blue',
  links_extracted: 'cyan',
  processing: 'yellow',
  completed: 'green',
  failed: 'red',
};

const PAGE_SIZE = 50;

export function ProjectsPage() {
  const [activePage, setActivePage] = useState(1);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<ProjectStatus | null>(null);
  const [typeFilter, setTypeFilter] = useState<ProjectType | null>(null);
  const [sortValue, setSortValue] = useState('updated_at:desc');
  const [sortBy, sortDirection] = sortValue.split(':') as [
    'name' | 'created_at' | 'updated_at' | 'status' | 'project_type',
    'asc' | 'desc',
  ];
  const { data, isLoading, error } = useProjects({
    page: activePage,
    pageSize: PAGE_SIZE,
    searchQuery: searchQuery.trim(),
    status: statusFilter || undefined,
    projectType: typeFilter || undefined,
    sortBy,
    sortDirection,
  });
  const [modalOpened, { open: openModal, close: closeModal }] = useDisclosure(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const modals = useModals();
  const deleteProjectMutation = useDeleteProject();
  const totalPages = data ? Math.max(1, Math.ceil(data.meta.total_items / data.meta.per_page)) : 1;
  const resetToFirstPage = () => setActivePage(1);

  const openDeleteModal = (project: Project) =>
    modals.openConfirmModal({
      title: 'Delete Project',
      centered: true,
      children: (
        <Text size="sm">
          Are you sure you want to delete the project "<strong>{project.name}</strong>"? This action is irreversible and
          will delete all associated data.
        </Text>
      ),
      labels: { confirm: 'Delete Project', cancel: 'Cancel' },
      confirmProps: { color: 'red' },
      onConfirm: () => deleteProjectMutation.mutate(project.id),
    });

  const handleOpenCreateModal = () => {
    setSelectedProject(null);
    openModal();
  };

  const handleOpenEditModal = (project: Project) => {
    setSelectedProject(project);
    openModal();
  };

  const rows = data?.data.map((project) => (
    <Table.Tr key={project.id}>
      <Table.Td>
        <Text fw={500}>{project.name}</Text>
        <Text size="xs" c="dimmed">
          {project.id}
        </Text>
      </Table.Td>
      <Table.Td>
        <Badge color={statusColors[project.status]} variant="light">
          {project.status.replace('_', ' ')}
        </Badge>
      </Table.Td>
      <Table.Td>{formatDate(project.updated_at)}</Table.Td>
      <Table.Td>
        <Group gap="xs">
          <ActionIcon
            component={Link}
            to={`/projects/${project.id}`}
            variant="subtle"
            aria-label={`View project ${project.name}`}
          >
            <IconEye size={16} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            onClick={() => handleOpenEditModal(project)}
            aria-label={`Edit project ${project.name}`}
          >
            <IconPencil size={16} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={() => openDeleteModal(project)}
            aria-label={`Delete project ${project.name}`}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  ));

  const loadingRows = Array.from({ length: 3 }).map((_, index) => (
    <Table.Tr key={index}>
      <Table.Td>
        <Skeleton height={8} mt={6} width="70%" radius="xl" />
        <Skeleton height={8} mt={6} width="40%" radius="xl" />
      </Table.Td>
      <Table.Td>
        <Skeleton height={12} mt={6} width="50px" radius="xl" />
      </Table.Td>
      <Table.Td>
        <Skeleton height={8} mt={6} width="60%" radius="xl" />
      </Table.Td>
      <Table.Td>
        <Skeleton height={16} width={16} radius="sm" />
        <Skeleton height={16} ml={8} width={16} radius="sm" />
      </Table.Td>
    </Table.Tr>
  ));

  return (
    <>
      <ProjectModal opened={modalOpened} onClose={closeModal} project={selectedProject} />
      <Stack>
        <Group justify="space-between">
          <Title order={1}>Projects</Title>
          <Button onClick={handleOpenCreateModal}>Create New Project</Button>
        </Group>

        {error && <Text color="red">Failed to load projects: {error.message}</Text>}

        <Group align="end">
          <TextInput
            label="Search"
            placeholder="Project name or ID"
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.currentTarget.value);
              resetToFirstPage();
            }}
            style={{ flex: 1, minWidth: 220 }}
          />
          <Select
            label="Status"
            placeholder="All statuses"
            clearable
            value={statusFilter}
            onChange={(value) => {
              setStatusFilter(value as ProjectStatus | null);
              resetToFirstPage();
            }}
            data={[
              { value: 'draft', label: 'Draft' },
              { value: 'search_params_generated', label: 'Search params generated' },
              { value: 'selector_generated', label: 'Selector generated' },
              { value: 'links_extracted', label: 'Links extracted' },
              { value: 'processing', label: 'Processing' },
              { value: 'completed', label: 'Completed' },
              { value: 'failed', label: 'Failed' },
            ]}
          />
          <Select
            label="Type"
            placeholder="All types"
            clearable
            value={typeFilter}
            onChange={(value) => {
              setTypeFilter(value as ProjectType | null);
              resetToFirstPage();
            }}
            data={[
              { value: 'lorebook', label: 'Lorebook' },
              { value: 'character', label: 'Character' },
            ]}
          />
          <Select
            label="Sort"
            value={sortValue}
            onChange={(value) => {
              setSortValue(value || 'updated_at:desc');
              resetToFirstPage();
            }}
            data={[
              { value: 'updated_at:desc', label: 'Last updated: newest' },
              { value: 'updated_at:asc', label: 'Last updated: oldest' },
              { value: 'created_at:desc', label: 'Created: newest' },
              { value: 'created_at:asc', label: 'Created: oldest' },
              { value: 'name:asc', label: 'Name: A-Z' },
              { value: 'name:desc', label: 'Name: Z-A' },
              { value: 'status:asc', label: 'Status: A-Z' },
              { value: 'project_type:asc', label: 'Type: A-Z' },
            ]}
          />
        </Group>

        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name / ID</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Last Updated</Table.Th>
              <Table.Th>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading ? (
              loadingRows
            ) : rows?.length ? (
              rows
            ) : (
              <Table.Tr>
                <Table.Td colSpan={4}>
                  <Text c="dimmed" ta="center">
                    No projects found.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>

        {!isLoading && data && data.meta.total_items > PAGE_SIZE && (
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              Showing {(data.meta.current_page - 1) * data.meta.per_page + 1}-
              {Math.min(data.meta.current_page * data.meta.per_page, data.meta.total_items)} of{' '}
              {data.meta.total_items} projects
            </Text>
            <Pagination value={activePage} onChange={setActivePage} total={totalPages} />
          </Group>
        )}
      </Stack>
    </>
  );
}
